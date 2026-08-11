"""Post-transition side effects shared by both execution paths.

A transition changes state through exactly one helper:
:func:`apply_transition`. Both the direct transition API and the approval
decisions route through it, guaranteeing that audit events and approval
requirements are created atomically with every state change.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from workflow_kit.approvals.requirements import ApprovalContext, resolve_approvers
from workflow_kit.audit.service import record_event
from workflow_kit.events.service import emit_event
from workflow_kit.events.types import EventType
from workflow_kit.models.approval import Approval, ApprovalStatus
from workflow_kit.models.history import WorkflowEventType


def _terminal_event(transition: Any) -> EventType:
    """Map a terminal transition to its domain event.

    A transition whose action is ``reject`` or ``cancel`` records the matching
    semantic outcome; every other terminal transition completes the workflow.
    """
    if transition.name == "reject":
        return EventType.WORKFLOW_REJECTED
    if transition.name == "cancel":
        return EventType.WORKFLOW_CANCELLED
    return EventType.WORKFLOW_COMPLETED


def apply_transition(
    locked: Any,
    workflow: Any,
    transition: Any,
    *,
    user: Any = None,
    reason: str = "",
) -> Any:
    """Persist ``transition`` on a locked execution and record its events.

    ``locked`` must already be an execution row selected with
    ``select_for_update`` (or otherwise under the caller's transaction). This
    function is only ever called inside an atomic block so the state change,
    the audit event and the approval record are committed together.
    """
    is_completion = workflow.is_terminal(transition.target)
    update_fields = ["current_state", "updated_at"]
    if is_completion:
        locked.completed_at = timezone.now()
        update_fields.append("completed_at")
    locked.current_state = transition.target
    locked.save(update_fields=update_fields)

    record_event(
        locked,
        event_type=WorkflowEventType.TRANSITION_EXECUTED,
        action=transition.name,
        source_state=transition.source,
        target_state=transition.target,
        user=user,
        reason=reason,
    )
    emit_event(
        EventType.WORKFLOW_TRANSITIONED,
        locked,
        workflow=workflow.name,
        source_state=transition.source,
        target_state=transition.target,
        action=transition.name,
        user=user,
        reason=reason,
    )

    if is_completion:
        record_event(
            locked,
            event_type=WorkflowEventType.WORKFLOW_COMPLETED,
            action=transition.name,
            source_state=transition.source,
            target_state=transition.target,
            user=user,
            reason=reason,
        )
        emit_event(
            _terminal_event(transition),
            locked,
            workflow=workflow.name,
            source_state=transition.source,
            target_state=transition.target,
            action=transition.name,
            user=user,
            reason=reason,
        )
    else:
        _create_step_approvals(
            locked, workflow, transition.target, action=transition.name, actor=user
        )
    return locked


def _create_step_approvals(
    locked: Any,
    workflow: Any,
    step: str,
    *,
    action: str = "",
    actor: Any = None,
) -> None:
    """Create the pending approvals guarding ``step`` from its requirement.

    Each declared approver of the step's
    :class:`~workflow_kit.approvals.requirements.ApprovalRequirement` results
    in one :class:`Approval`; the voting mode, quorum and self-approval policy
    are persisted on each approval's ``assignment`` so decisions never depend
    on the definition changing later.
    """
    requirement = workflow.approval_requirement(step)
    context = ApprovalContext.build(workflow, locked, step)
    assignments = resolve_approvers(requirement, context)
    if not assignments:
        assignments = [{"type": "any"}]
    due_at = timezone.now() + requirement.sla if requirement.sla is not None else None

    for index, slot in enumerate(assignments, start=1):
        assignment = dict(slot)
        assignment["mode"] = requirement.mode
        assignment["quorum"] = requirement.quorum
        assignment["allow_self"] = requirement.allow_self
        assignment["label"] = requirement.label

        approval = Approval.objects.create(
            execution=locked,
            step=step,
            status=ApprovalStatus.PENDING,
            mode=requirement.mode,
            order=index,
            assignment=assignment,
            allow_self=requirement.allow_self,
            due_at=due_at,
            action=action,
        )
        record_event(
            locked,
            event_type=WorkflowEventType.APPROVAL_REQUIRED,
            action=action,
            source_state=step,
            target_state="",
            user=actor,
            metadata={
                "approval": approval.pk,
                "mode": requirement.mode,
                "order": index,
            },
        )
        emit_event(
            EventType.APPROVAL_CREATED,
            locked,
            workflow=workflow.name,
            source_state=step,
            target_state="",
            action=action,
            user=actor,
            metadata={"approval": approval.pk, "order": index},
        )
