"""Approval decision service.

The approval engine is a thin, transactional layer over the workflow engine:
pending :class:`~workflow_kit.models.Approval` records guard each current step,
and :func:`approve_execution` / :func:`reject_execution` decide them by
executing the corresponding transition through the same engine path as a direct
transition call.

Phase 9 adds the *step requirement* layer: a step may declare any-of / all-of /
quorum modes with one approval per declared approver. Deciding a single
approval only advances (or rejects) the execution once the whole step's
requirement is satisfied; sibling approvals are cancelled when the step is
resolved. Delegation (:func:`delegate_approval`), escalation
(:func:`escalate_execution`) and SLA tracking (:func:`overdue_approvals`) build
on the same model.

Authorization always comes from the Phase 2 permission system — the approval
layer never decides permissions itself.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from workflow_kit.audit.service import _persistable_user, record_event
from workflow_kit.conf import settings as workflow_settings
from workflow_kit.engine.effects import apply_transition
from workflow_kit.engine.versioning import get_workflow_for_execution
from workflow_kit.events.service import emit_event
from workflow_kit.events.types import EventType
from workflow_kit.exceptions import (
    ApprovalNotPendingError,
    PermissionDeniedError,
    WorkflowAlreadyCompletedError,
)
from workflow_kit.models.approval import Approval, ApprovalMode, ApprovalStatus
from workflow_kit.models.delegation import WorkflowDelegation
from workflow_kit.models.history import WorkflowEventType
from workflow_kit.permissions.evaluate import is_authorized

# The decision transitions recognised by the approval engine.
_APPROVE_ACTION = "approve"
_REJECT_ACTION = "reject"


# -- Queries ------------------------------------------------------------------


def pending_approvals(execution: Any) -> QuerySet[Approval]:
    """Return the approvals waiting for a decision for ``execution``."""
    return Approval.objects.filter(
        execution=execution,
        status=ApprovalStatus.PENDING,
    ).order_by("step", "order", "created_at", "id")


def step_approvals(execution: Any, step: str) -> QuerySet[Approval]:
    """Return every approval (decided or pending) for ``step`` of ``execution``."""
    return Approval.objects.filter(execution=execution, step=step).order_by("order", "id")


def overdue_approvals(*, workflow_name: str | None = None) -> QuerySet[Approval]:
    """Return still-pending approvals past their SLA ``due_at`` deadline.

    ``workflow_name`` optionally narrows the search to one workflow. This is the
    hook escalation tooling / tasks call to find work that slipped its SLA.
    """
    queryset = Approval.objects.filter(
        status=ApprovalStatus.PENDING,
        due_at__isnull=False,
        due_at__lt=timezone.now(),
    ).order_by("due_at", "id")
    if workflow_name is not None:
        queryset = queryset.filter(execution__workflow_name=workflow_name)
    return queryset.select_related("execution")


# -- Slot matching ------------------------------------------------------------


def _user_group_names(user: Any) -> frozenset[str]:
    groups = getattr(user, "groups", None)
    if groups is None:
        return frozenset()
    return frozenset(groups.values_list("name", flat=True))


def _assignment_matches(approval: Approval, user: Any) -> bool:
    """Return whether ``user`` may fill ``approval``'s slot by assignment."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    assignment = approval.assignment or {}
    kind = assignment.get("type")
    if kind == "any":
        return True
    if kind == "group":
        return assignment.get("name") in _user_group_names(user)
    if kind == "user":
        username = getattr(user, "username", None)
        return bool(username) and username == assignment.get("username")
    return False


def _delegation_for(approval: Approval, user: Any) -> WorkflowDelegation | None:
    """Return an active delegation letting ``user`` fill ``approval``'s slot."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    delegations = WorkflowDelegation.objects.filter(
        execution_id=approval.execution_id,
        grantee=user,
        active=True,
    )
    for delegation in delegations:
        if not delegation.is_active:
            continue
        if delegation.step and delegation.step != approval.step:
            continue
        if delegation.granter_id is None:
            continue
        if _assignment_matches(approval, delegation.granter):
            return delegation
    return None


def _can_act(user: Any) -> bool:
    """Return whether ``user`` may act at all (authenticated or superuser)."""
    if user is None:
        return False
    return bool(getattr(user, "is_authenticated", False))


def _candidate_slot(
    execution: Any, step: str, user: Any
) -> tuple[Approval, WorkflowDelegation | None]:
    """Pick the pending approval of ``step`` that ``user`` may decide.

    Prefers a directly assigned slot, then a slot the user can fill through an
    active delegation. Raises :class:`ApprovalNotPendingError` when ``user``
    has nothing pending to decide (or has already decided this step).
    """
    if not _can_act(user):
        raise PermissionDeniedError("An authenticated user is required to decide an approval.")
    slots = list(
        Approval.objects.filter(
            execution=execution,
            step=step,
            status=ApprovalStatus.PENDING,
        ).order_by("order", "id")
    )
    if not slots:
        raise ApprovalNotPendingError(
            f"No pending approval exists for step '{step}' in workflow '{execution.workflow_name}'."
        )

    if Approval.objects.filter(
        execution=execution,
        step=step,
        approver=user,
        status__in=[ApprovalStatus.APPROVED, ApprovalStatus.REJECTED],
    ).exists():
        raise ApprovalNotPendingError(f"You have already decided step '{step}'.")

    for slot in slots:
        if _assignment_matches(slot, user):
            return slot, None
    for slot in slots:
        delegation = _delegation_for(slot, user)
        if delegation is not None:
            return slot, delegation
    raise ApprovalNotPendingError(
        f"No pending approval of step '{step}' matches user '{getattr(user, 'username', user)}'."
    )


def _self_approval_allowed(execution: Any, slot: Approval, user: Any) -> bool:
    """Apply the step's self-approval policy against the initiator."""
    assignment = slot.assignment or {}
    if assignment.get("allow_self", True):
        return True
    initiator = execution.initiated_by
    if initiator is None or user is None:
        return True
    return bool(initiator.pk != getattr(user, "pk", None))


# -- Step resolution ----------------------------------------------------------


def _step_modes(approval: Approval, execution: Any, step: str) -> tuple[str, int]:
    """Resolve the voting config for ``step`` from its first approval."""
    representatives = step_approvals(execution, step).first()
    representative = approval if representatives is None else representatives
    assignment = representative.assignment or {}
    mode = representative.mode or assignment.get("mode", ApprovalMode.ALL)
    quorum = int(assignment.get("quorum", 1) or 1)
    return mode, quorum


def _step_outcome(execution: Any, step: str, latest: Approval) -> str:
    """Decide whether ``step`` advances, rejects or stays pending.

    Returns one of ``"advance"``, ``"reject"`` or ``"partial"``.
    """
    mode, quorum = _step_modes(latest, execution, step)
    approvals = list(step_approvals(execution, step))
    pending = [a for a in approvals if a.status == ApprovalStatus.PENDING]
    has_rejection = any(a.status == ApprovalStatus.REJECTED for a in approvals)

    if mode == ApprovalMode.ANY:
        return "advance" if latest.status == ApprovalStatus.APPROVED else "reject"
    if mode == ApprovalMode.ALL:
        if has_rejection:
            return "reject"
        return "advance" if not pending else "partial"
    # QUORUM
    if has_rejection:
        return "reject"
    approved = sum(1 for a in approvals if a.status == ApprovalStatus.APPROVED)
    if approved >= quorum:
        return "advance"
    if not pending:
        return "reject"
    return "partial"


def _cancel_siblings(execution: Any, step: str, *, keep_id: int | None = None) -> None:
    """Cancel the still-pending approvals of ``step`` (except ``keep_id``)."""
    siblings = Approval.objects.filter(
        execution=execution,
        step=step,
        status=ApprovalStatus.PENDING,
    )
    if keep_id is not None:
        siblings = siblings.exclude(pk=keep_id)
    for sibling in siblings:
        sibling.status = ApprovalStatus.CANCELLED
        sibling.save(update_fields=["status", "updated_at"])
        record_event(
            execution,
            event_type=WorkflowEventType.APPROVAL_CANCELLED,
            action="",
            source_state=step,
            target_state="",
            metadata={"approval": sibling.pk},
        )
        emit_event(
            EventType.APPROVAL_CANCELLED,
            execution,
            workflow=execution.workflow_name,
            source_state=step,
            target_state="",
            metadata={"approval": sibling.pk},
        )


# -- Decisions ----------------------------------------------------------------


def _approval_event(event_type: WorkflowEventType) -> EventType:
    """Map an audit event code to its domain event type."""
    if event_type == WorkflowEventType.APPROVAL_APPROVED:
        return EventType.APPROVAL_APPROVED
    if event_type == WorkflowEventType.APPROVAL_REJECTED:
        return EventType.APPROVAL_REJECTED
    return EventType.APPROVAL_CANCELLED


def approve_execution(execution: Any, *, user: Any = None, reason: str = "") -> Approval:
    """Approve one pending approval of the current step.

    When the step's requirement (all-of, any-of or quorum) is satisfied, the
    execution advances through the ``approve`` transition; otherwise only the
    vote is recorded. Returns the updated
    :class:`~workflow_kit.models.approval.Approval`.
    """
    return _decide(
        execution,
        action=_APPROVE_ACTION,
        status=ApprovalStatus.APPROVED,
        event_type=WorkflowEventType.APPROVAL_APPROVED,
        user=user,
        reason=reason,
    )


def reject_execution(execution: Any, *, user: Any = None, reason: str = "") -> Approval:
    """Reject one pending approval of the current step.

    A rejection settles the step: sibling approvals are cancelled and the
    execution moves to its rejection state through the ``reject`` transition.
    Returns the updated :class:`~workflow_kit.models.approval.Approval`.
    """
    return _decide(
        execution,
        action=_REJECT_ACTION,
        status=ApprovalStatus.REJECTED,
        event_type=WorkflowEventType.APPROVAL_REJECTED,
        user=user,
        reason=reason,
    )


def _decide(
    execution: Any,
    *,
    action: str,
    status: ApprovalStatus,
    event_type: WorkflowEventType,
    user: Any = None,
    reason: str = "",
) -> Approval:
    """Decide one pending approval and, when satisfied, resolve the step."""

    def _apply() -> Approval:
        from workflow_kit.models import WorkflowExecution

        locked = WorkflowExecution.objects.select_for_update().get(pk=execution.pk)
        current = locked.current_state

        workflow = get_workflow_for_execution(locked)
        if workflow.is_terminal(current) or locked.is_completed:
            raise WorkflowAlreadyCompletedError(
                f"Workflow '{workflow.name}' is already completed in state '{current}'."
            )

        transition = workflow.resolve_transition(locked, action, user=user)
        slot, delegation = _candidate_slot(locked, current, user)
        locked_slot = Approval.objects.select_for_update().get(pk=slot.pk)
        if locked_slot.status != ApprovalStatus.PENDING:
            raise ApprovalNotPendingError(
                f"Approval '{locked_slot.pk}' for step '{current}' was already decided."
            )

        # Authorization is evaluated against the delegation's granter so a
        # granted approval transfers the granter's rights, never the proxy's.
        authority = delegation.granter if delegation is not None else user
        if not is_authorized(authority, workflow, locked, transition):
            raise PermissionDeniedError(f"User is not authorized to execute transition '{action}'.")
        if not _self_approval_allowed(locked, locked_slot, authority):
            raise PermissionDeniedError(
                f"Self-approval is not allowed for this step of workflow '{workflow.name}'."
            )

        locked_slot.status = status
        locked_slot.approver = _persistable_user(user)
        locked_slot.delegation = delegation
        locked_slot.action = action
        locked_slot.reason = reason
        locked_slot.save(
            update_fields=["status", "approver", "delegation", "action", "reason", "updated_at"]
        )

        record_event(
            locked,
            event_type=event_type,
            action=action,
            source_state=current,
            target_state="",
            user=user,
            reason=reason,
            metadata={"approval": locked_slot.pk},
        )
        emit_event(
            _approval_event(event_type),
            locked,
            workflow=workflow.name,
            source_state=current,
            target_state="",
            action=action,
            user=user,
            reason=reason,
            metadata={"approval": locked_slot.pk},
        )

        outcome = _step_outcome(locked, current, locked_slot)
        if outcome == "partial":
            _mirror(execution, locked)
            return locked_slot

        transition_to_run = _APPROVE_ACTION if outcome == "advance" else _REJECT_ACTION
        resolved = workflow.resolve_transition(locked, transition_to_run, user=authority)
        if not is_authorized(authority, workflow, locked, resolved):
            raise PermissionDeniedError(
                f"User is not authorized to execute transition '{transition_to_run}'."
            )
        _cancel_siblings(locked, current, keep_id=locked_slot.pk)
        apply_transition(locked, workflow, resolved, user=user, reason=reason)

        _mirror(execution, locked)
        return locked_slot

    from workflow_kit.events import capture

    if workflow_settings.ATOMIC_TRANSITIONS:
        with capture(), transaction.atomic():
            return _apply()
    return _apply()


def _mirror(execution: Any, locked: Any) -> None:
    """Mirror fresh execution state back onto the caller's instance."""
    execution.current_state = locked.current_state
    execution.completed_at = locked.completed_at
    execution.updated_at = locked.updated_at


# -- Delegation ---------------------------------------------------------------


def delegate_approval(
    execution: Any,
    *,
    granter: Any,
    grantee: Any,
    reason: str = "",
    step: str = "",
    expires_at: Any = None,
) -> WorkflowDelegation:
    """Forward ``granter``'s approval right on ``step`` to ``grantee``.

    ``step`` may be empty to cover every step of ``execution``; ``expires_at``
    optionally limits the grant in time. ``granter`` must currently be able to
    decide a pending approval of ``execution``.
    """
    if not _persistable_user(granter):
        raise PermissionDeniedError("Delegation requires an authenticated granter.")
    if _persistable_user(grantee) is None:
        raise PermissionDeniedError("Delegation requires a persisted grantee user.")

    def _apply() -> WorkflowDelegation:
        from workflow_kit.models import WorkflowExecution

        locked = WorkflowExecution.objects.select_for_update().get(pk=execution.pk)
        workflow = get_workflow_for_execution(locked)
        if workflow.is_terminal(locked.current_state) or locked.is_completed:
            raise WorkflowAlreadyCompletedError(f"Workflow '{workflow.name}' is already completed.")
        scope_steps = [locked.current_state] if not step else [step]
        can_delegate = any(
            _assignment_matches(slot, granter)
            for current in scope_steps
            for slot in Approval.objects.filter(
                execution=locked,
                step=current,
                status=ApprovalStatus.PENDING,
            )
        )
        if not can_delegate:
            raise PermissionDeniedError(
                f"User {'granter'} has nothing to delegate for this execution."
            )

        delegation = WorkflowDelegation.objects.create(
            execution=locked,
            granter=granter,
            grantee=grantee,
            step=step,
            reason=reason,
            expires_at=expires_at,
            active=True,
        )
        record_event(
            locked,
            event_type=WorkflowEventType.APPROVAL_DELEGATED,
            action="delegate",
            source_state=locked.current_state,
            target_state=locked.current_state,
            user=granter,
            reason=reason,
            metadata={"delegation": delegation.pk, "grantee": getattr(grantee, "pk", None)},
        )
        emit_event(
            EventType.APPROVAL_DELEGATED,
            locked,
            workflow=workflow.name,
            source_state=locked.current_state,
            target_state=locked.current_state,
            action="delegate",
            user=granter,
            reason=reason,
            metadata={"delegation": delegation.pk},
        )
        return delegation

    from workflow_kit.events import capture

    if workflow_settings.ATOMIC_TRANSITIONS:
        with capture(), transaction.atomic():
            return _apply()
    return _apply()


def revoke_delegation(delegation: WorkflowDelegation, *, user: Any = None) -> WorkflowDelegation:
    """Revoke an active delegation; returns the record for chaining."""
    delegation.revoke(user=user)
    return delegation


# -- Escalation ---------------------------------------------------------------


def escalate_execution(
    execution: Any,
    *,
    approver: Any,
    user: Any = None,
    reason: str = "",
) -> Approval:
    """Escalate the current step to a single escalation approver.

    The pending approvals of the current step are cancelled and replaced by one
    approval assigned to ``approver`` (group name, username, user, resolver or
    callable) using any-of mode, so that approver alone decides the step.
    ``user`` is recorded as the escalation actor and must be authorized for the
    step's ``approve`` transition.
    """

    def _apply() -> Approval:
        from workflow_kit.approvals.requirements import (
            ApprovalContext,
            ApprovalRequirement,
            resolve_approvers,
        )
        from workflow_kit.models import WorkflowExecution

        locked = WorkflowExecution.objects.select_for_update().get(pk=execution.pk)
        current = locked.current_state
        workflow = get_workflow_for_execution(locked)
        if workflow.is_terminal(current) or locked.is_completed:
            raise WorkflowAlreadyCompletedError(
                f"Workflow '{workflow.name}' is already completed in state '{current}'."
            )

        transition = workflow.resolve_transition(locked, _APPROVE_ACTION, user=user)
        if not is_authorized(user, workflow, locked, transition):
            raise PermissionDeniedError("User is not authorized to escalate this step.")

        pending = list(
            Approval.objects.filter(
                execution=locked,
                step=current,
                status=ApprovalStatus.PENDING,
            ).order_by("order", "id")
        )
        if not pending:
            raise ApprovalNotPendingError(
                f"No pending approval exists for step '{current}' to escalate."
            )

        context = ApprovalContext.build(workflow, locked, current)
        slots = resolve_approvers(
            ApprovalRequirement(mode=ApprovalMode.ANY, approvers=[approver]),
            context,
        )
        if not slots:
            raise ApprovalNotPendingError("The escalation approver could not be resolved.")

        _cancel_siblings(locked, current)
        slot = dict(slots[0])
        slot["mode"] = ApprovalMode.ANY
        slot["quorum"] = 1
        slot["allow_self"] = True
        slot["escalated"] = True

        next_order = (Approval.objects.filter(execution=locked, step=current).count() or 0) + 1
        escalated = Approval.objects.create(
            execution=locked,
            step=current,
            status=ApprovalStatus.PENDING,
            mode=ApprovalMode.ANY,
            order=next_order,
            assignment=slot,
            allow_self=True,
            action=_APPROVE_ACTION,
        )
        record_event(
            locked,
            event_type=WorkflowEventType.APPROVAL_ESCALATED,
            action="escalate",
            source_state=current,
            target_state=current,
            user=user,
            reason=reason,
            metadata={"approval": escalated.pk, "to": slot.get("name", slot.get("username", ""))},
        )
        emit_event(
            EventType.APPROVAL_ESCALATED,
            locked,
            workflow=workflow.name,
            source_state=current,
            target_state=current,
            action="escalate",
            user=user,
            reason=reason,
            metadata={"approval": escalated.pk},
        )
        return escalated

    from workflow_kit.events import capture

    if workflow_settings.ATOMIC_TRANSITIONS:
        with capture(), transaction.atomic():
            return _apply()
    return _apply()
