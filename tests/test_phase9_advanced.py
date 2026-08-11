"""Phase 9 tests: advanced approval workflows.

Covers approval requirements (all-of / any-of / quorum modes), dynamic
approver resolvers, self-approval rules, delegation, escalation, SLA/overdue
tracking and concurrency guarantees for parallel steps.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from workflow_kit import (
    ApprovalMode,
    ApprovalNotPendingError,
    ApprovalRequirement,
    ApproverResolver,
    PermissionDeniedError,
    Transition,
    Workflow,
    WorkflowAlreadyCompletedError,
)
from workflow_kit.engine import registry
from workflow_kit.models import Approval, ApprovalStatus, WorkflowExecution

from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db

# -- fixtures -----------------------------------------------------------------


def _user(username: str, *groups: str) -> Any:
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={"password": "test-password-123"},
    )
    for name in groups:
        _group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(_group)
    return user


@pytest.fixture
def invoice() -> Invoice:
    return Invoice.objects.create(number="INV-P9", vendor="Acme", amount="500.00")


@pytest.fixture
def parallel_workflow():
    """A single review step guarded by a configurable requirement."""

    def _build(name: str = "p9_flow", requirement=None):
        workflow = Workflow(
            name=name,
            initial="draft",
            states=["draft", "review", "approved", "rejected"],
            transitions=[
                ("submit", "draft", "review"),
                Transition("approve", "review", "approved"),
                Transition("reject", "review", "rejected"),
            ],
            approval_requirements={"review": requirement} if requirement else None,
        )
        return workflow

    yield _build
    for workflow in registry.all_workflows():
        if workflow.name.startswith("p9_"):
            registry.unregister(workflow.name)


def _started(workflow, invoice) -> WorkflowExecution:
    execution = workflow.start(invoice)
    workflow.transition(execution, "submit")
    return execution


def _step_approvals(execution, step="review"):
    return list(Approval.objects.filter(execution=execution, step=step).order_by("order", "id"))


def _register_tmp(workflow):
    """Return a workflow registered under a unique name not colliding with the suite."""

    def _teardown():
        registry.unregister(workflow.name)

    return workflow, _teardown


# --------------------------------------------------------------------------- #
# Requirement declaration and approval shapes
# --------------------------------------------------------------------------- #


def test_default_requirement_keeps_single_any_approval(invoice):
    workflow = Workflow(
        name="p9_default",
        initial="draft",
        states=["draft", "review", "approved"],
        transitions=[("submit", "draft", "review"), ("approve", "review", "approved")],
    )
    execution = _started(workflow, invoice)
    approvals = _step_approvals(execution)
    assert len(approvals) == 1
    assert approvals[0].mode == ApprovalMode.ALL
    assert approvals[0].order == 1
    assert approvals[0].assignment["type"] == "any"
    assert approvals[0].is_pending
    registry.unregister("p9_default")


def test_parallel_requirement_creates_one_approval_per_approver(invoice):
    requirement = ApprovalRequirement(approvers=["Manager", "Finance"])
    workflow = Workflow(
        name="p9_parallel_creation",
        initial="draft",
        states=["draft", "review", "approved"],
        transitions=[("submit", "draft", "review"), ("approve", "review", "approved")],
        approval_requirements={"review": requirement},
    )
    execution = _started(workflow, invoice)
    approvals = _step_approvals(execution)
    assert len(approvals) == 2
    assert [a.assignment["type"] for a in approvals] == ["group", "group"]
    assert [a.assignment["name"] for a in approvals] == ["Manager", "Finance"]
    assert [a.order for a in approvals] == [1, 2]
    registry.unregister("p9_parallel")


def test_resolver_materializes_group_assignment(invoice):
    class FinanceResolver(ApproverResolver):
        def resolve(self, context: Any):
            return "Finance"

    workflow = Workflow(
        name="p9_resolver",
        initial="draft",
        states=["draft", "review", "approved"],
        transitions=[
            ("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission=None),
        ],
        approval_requirements={"review": ApprovalRequirement(approvers=[FinanceResolver()])},
    )
    execution = _started(workflow, invoice)
    approvals = _step_approvals(execution)
    assert len(approvals) == 1
    assert approvals[0].assignment["type"] == "group"
    assert approvals[0].assignment["name"] == "Finance"
    registry.unregister("p9_resolver")


def test_callable_approver_resolves_to_user(invoice):
    signer = _user("signer_user")

    def _approver(context: Any) -> Any:
        assert context.object == invoice
        return signer

    workflow = Workflow(
        name="p9_callable",
        initial="draft",
        states=["draft", "review", "approved"],
        transitions=[
            ("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission=None),
        ],
        approval_requirements={
            "review": ApprovalRequirement(approvers=[_approver]),
        },
    )
    execution = _started(workflow, invoice)
    approvals = _step_approvals(execution)
    assert len(approvals) == 1
    assert approvals[0].assignment["type"] == "user"
    assert approvals[0].assignment["username"] == "signer_user"
    with pytest.raises(ApprovalNotPendingError):
        execution.approve(_user("other_user"))
    execution.approve(signer)
    assert execution.current_state == "approved"
    registry.unregister("p9_callable")


# --------------------------------------------------------------------------- #
# all-of (parallel)
# --------------------------------------------------------------------------- #


def test_all_of_advances_only_after_every_approver(
    parallel_workflow,
    invoice,
):
    workflow = parallel_workflow(
        "p9_allof",
        ApprovalRequirement(approvers=["Manager", "Finance"]),
    )
    execution = _started(workflow, invoice)
    manager, finance = _user("m9", "Manager"), _user("f9", "Finance")

    first = execution.approve(manager, reason="ok-m")
    assert first.status == ApprovalStatus.APPROVED
    assert execution.current_state == "review"
    assert len(execution.pending_approvals()) == 1

    second = execution.approve(finance, reason="ok-f")
    assert second.status == ApprovalStatus.APPROVED
    assert execution.current_state == "approved"
    assert execution.is_completed is True
    assert list(execution.pending_approvals()) == []


def test_all_of_partial_votes_do_not_advance(parallel_workflow, invoice):
    workflow = parallel_workflow(
        "p9_allof_partial", ApprovalRequirement(approvers=["Manager", "Finance"])
    )
    execution = _started(workflow, invoice)
    execution.approve(_user("m9a", "Manager"))
    fresh = WorkflowExecution.objects.get(pk=execution.pk)
    assert fresh.current_state == "review"
    statuses = [a.status for a in _step_approvals(execution)]
    assert statuses == [ApprovalStatus.APPROVED, ApprovalStatus.PENDING]


def test_all_of_rejection_rejects_and_cancels_siblings(parallel_workflow, invoice):
    workflow = parallel_workflow(
        "p9_allof_reject", ApprovalRequirement(approvers=["Manager", "Finance"])
    )
    execution = _started(workflow, invoice)
    manager, finance = _user("m9r", "Manager"), _user("f9r", "Finance")

    execution.approve(manager)
    rejected = execution.reject(finance, reason="quote missing")

    assert rejected.status == ApprovalStatus.REJECTED
    assert execution.current_state == "rejected"
    assert execution.is_completed is True
    statuses = {a.status for a in _step_approvals(execution)}
    assert statuses == {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}


def test_user_cannot_approve_same_parallel_step_twice(parallel_workflow, invoice):
    workflow = parallel_workflow("p9_twice", ApprovalRequirement(approvers=["Manager", "Member"]))
    execution = _started(workflow, invoice)
    manager = _user("m9t", "Manager", "Member")
    execution.approve(manager)
    with pytest.raises(ApprovalNotPendingError):
        execution.approve(manager)


def test_unassigned_user_cannot_fill_a_slot(parallel_workflow, invoice):
    workflow = parallel_workflow(
        "p9_slotful", ApprovalRequirement(approvers=["Manager", "Finance"])
    )
    execution = _started(workflow, invoice)
    outsider = _user("o9", "Guest")
    with pytest.raises(ApprovalNotPendingError):
        execution.approve(outsider)
    assert execution.current_state == "review"


# --------------------------------------------------------------------------- #
# any-of
# --------------------------------------------------------------------------- #


def test_any_of_first_approval_advances_and_cancels_other_slot(parallel_workflow, invoice):
    workflow = parallel_workflow(
        "p9_anyof",
        ApprovalRequirement(mode=ApprovalMode.ANY, approvers=["Manager", "Finance"]),
    )
    execution = _started(workflow, invoice)
    execution.approve(_user("m9y", "Manager"))
    assert execution.current_state == "approved"
    statuses = {a.status for a in _step_approvals(execution)}
    assert statuses == {ApprovalStatus.APPROVED, ApprovalStatus.CANCELLED}


def test_any_of_first_rejection_rejects(parallel_workflow, invoice):
    workflow = parallel_workflow(
        "p9_anyof_reject",
        ApprovalRequirement(mode=ApprovalMode.ANY, approvers=["Manager", "Finance"]),
    )
    execution = _started(workflow, invoice)
    execution.reject(_user("f9yr", "Finance"), reason="abort")
    assert execution.current_state == "rejected"
    statuses = {a.status for a in _step_approvals(execution)}
    assert statuses == {ApprovalStatus.REJECTED, ApprovalStatus.CANCELLED}


# --------------------------------------------------------------------------- #
# quorum
# --------------------------------------------------------------------------- #


def test_quorum_reached_advances_and_cancels_remaining(parallel_workflow, invoice):
    workflow = parallel_workflow(
        "p9_quorum",
        ApprovalRequirement(
            mode=ApprovalMode.QUORUM, quorum=2, approvers=["Manager", "Finance", "Executive"]
        ),
    )
    execution = _started(workflow, invoice)
    execution.approve(_user("m9q", "Manager"))
    assert execution.current_state == "review"
    execution.approve(_user("f9q", "Finance"))
    assert execution.current_state == "approved"
    statuses = {a.status for a in _step_approvals(execution)}
    assert statuses == {
        ApprovalStatus.APPROVED,
        ApprovalStatus.APPROVED,
        ApprovalStatus.CANCELLED,
    }


def test_quorum_never_reached_when_all_decided_rejects(parallel_workflow, invoice):
    workflow = parallel_workflow(
        "p9_quorum_short",
        ApprovalRequirement(mode=ApprovalMode.QUORUM, quorum=3, approvers=["E1", "E2"]),
    )
    execution = _started(workflow, invoice)
    execution.approve(_user("e1", "E1"))
    assert execution.current_state == "review"
    execution.approve(_user("e2", "E2"))
    assert execution.current_state == "rejected"
    assert execution.is_completed is True


def test_quorum_single_rejection_rejects(parallel_workflow, invoice):
    workflow = parallel_workflow(
        "p9_quorum_veto",
        ApprovalRequirement(
            mode=ApprovalMode.QUORUM, quorum=2, approvers=["Manager", "Finance", "Executive"]
        ),
    )
    execution = _started(workflow, invoice)
    execution.approve(_user("m9v", "Manager"))
    execution.reject(_user("f9v", "Finance"), reason="veto")
    assert execution.current_state == "rejected"


# --------------------------------------------------------------------------- #
# user-assigned slots
# --------------------------------------------------------------------------- #


def test_user_assignment_slot_only_its_owner_can_approve(parallel_workflow, invoice):
    alice = _user("alice9")
    workflow = parallel_workflow("p9_user_slot", ApprovalRequirement(approvers=[alice]))
    execution = _started(workflow, invoice)
    approvals = _step_approvals(execution)
    assert approvals[0].assignment == {
        "type": "user",
        "username": "alice9",
        "mode": "ALL",
        "quorum": 1,
        "allow_self": True,
        "label": "",
    }
    with pytest.raises(ApprovalNotPendingError):
        execution.approve(_user("bob9"))
    execution.approve(alice)
    assert execution.current_state == "approved"


# --------------------------------------------------------------------------- #
# self-approval policy
# --------------------------------------------------------------------------- #


def test_self_approval_forbidden_for_initiator(parallel_workflow, invoice):
    workflow = parallel_workflow("p9_self_no", ApprovalRequirement(allow_self=False))
    alice = _user("alice_self")
    execution = workflow.start(invoice, user=alice)
    workflow.transition(execution, "submit")
    assert execution.initiated_by == alice

    with pytest.raises(PermissionDeniedError):
        execution.approve(alice)
    assert execution.current_state == "review"

    other = _user("other_self")
    execution.approve(other)
    assert execution.current_state == "approved"


def test_self_approval_allowed_by_default(parallel_workflow, invoice):
    workflow = parallel_workflow("p9_self_ok", ApprovalRequirement(allow_self=True))
    alice = _user("alice_ok")
    execution = workflow.start(invoice, user=alice)
    workflow.transition(execution, "submit")
    execution.approve(alice)
    assert execution.current_state == "approved"


# --------------------------------------------------------------------------- #
# delegation
# --------------------------------------------------------------------------- #


def test_delegate_lets_grantee_decide_slot(parallel_workflow, invoice):
    workflow = parallel_workflow("p9_delegation", ApprovalRequirement(approvers=["Manager"]))
    execution = _started(workflow, invoice)
    manager = _user("mgr_deleg", "Manager")
    proxy = _user("proxy_deleg")

    execution.delegate(granter=manager, grantee=proxy, reason="on leave")
    delegation = execution.delegations.get()
    assert delegation.granter == manager
    assert delegation.grantee == proxy

    decided = execution.approve(proxy, reason="proxy vote")
    assert decided.status == ApprovalStatus.APPROVED
    assert decided.delegation == delegation
    assert execution.current_state == "approved"


def test_delegation_without_scope_raises_for_unassigned_granter(parallel_workflow, invoice):
    workflow = parallel_workflow("p9_deleg_deny", ApprovalRequirement(approvers=["Manager"]))
    execution = _started(workflow, invoice)
    employee = _user("emp_deleg")
    proxy = _user("proxy2")
    with pytest.raises(PermissionDeniedError):
        execution.delegate(granter=employee, grantee=proxy)


def test_revoked_delegation_cannot_decide(parallel_workflow, invoice):
    workflow = parallel_workflow("p9_deleg_revoke", ApprovalRequirement(approvers=["Manager"]))
    execution = _started(workflow, invoice)
    manager = _user("mgr_revoke", "Manager")
    proxy = _user("proxy_revoke")
    delegation = execution.delegate(granter=manager, grantee=proxy)
    assert delegation.is_active is True
    delegation.revoke(user=proxy)
    assert delegation.is_active is False

    with pytest.raises(ApprovalNotPendingError):
        execution.approve(proxy)


def test_delegation_timeline_and_audit(parallel_workflow, invoice):
    workflow = parallel_workflow("p9_deleg_timeline", ApprovalRequirement(approvers=["Manager"]))
    execution = _started(workflow, invoice)
    manager = _user("mgr_tl", "Manager")
    proxy = _user("proxy_tl")
    execution.delegate(granter=manager, grantee=proxy, reason="on leave")

    timeline = execution.timeline()
    labels = [e.label for e in timeline]
    assert "Delegated" in labels
    history = execution.history()
    assert any(e.event_type == "approval_delegated" for e in history)


# --------------------------------------------------------------------------- #
# escalation
# --------------------------------------------------------------------------- #


def test_escalation_reassigns_step_to_single_approver(parallel_workflow, invoice):
    workflow = parallel_workflow(
        "p9_escalate", ApprovalRequirement(approvers=["Manager", "Finance"])
    )
    execution = _started(workflow, invoice)
    escalated = execution.escalate(
        approver="Executive", user=_user("f9e", "Finance"), reason="slipping"
    )

    assert escalated.assignment["type"] == "group"
    assert escalated.assignment["name"] == "Executive"
    assert escalated.assignment["escalated"] is True
    assert escalated.mode == ApprovalMode.ANY
    # The previous parallel slots are cancelled.
    statuses = {a.status for a in _step_approvals(execution)}
    assert statuses == {ApprovalStatus.CANCELLED, ApprovalStatus.PENDING}

    # Only the escalation approver can decide now.
    with pytest.raises(ApprovalNotPendingError):
        execution.approve(_user("finance_only", "Finance"))

    execution.approve(_user("exec_approver", "Executive"))
    assert execution.current_state == "approved"
    assert execution.is_completed is True


def test_escalation_records_audit(parallel_workflow, invoice):
    workflow = parallel_workflow("p9_escalate_audit", ApprovalRequirement(approvers=["Manager"]))
    execution = _started(workflow, invoice)
    execution.escalate(approver="Executive", user=_user("escalator"))
    history = execution.history()
    assert any(e.event_type == "approval_escalated" for e in history)
    timeline = execution.timeline()
    assert any(e.label == "Escalated" for e in timeline)


# --------------------------------------------------------------------------- #
# SLA / overdue
# --------------------------------------------------------------------------- #


def test_sla_deadline_recorded_and_overdue_detected(parallel_workflow, invoice):
    workflow = parallel_workflow("p9_sla", ApprovalRequirement(sla=timedelta(days=1)))
    execution = _started(workflow, invoice)
    approval = _step_approvals(execution)[0]
    assert approval.due_at is not None
    assert approval.is_overdue is False

    approval.due_at = timezone.now() - timedelta(hours=1)
    approval.save(update_fields=["due_at"])
    approval.refresh_from_db()
    assert approval.is_overdue is True

    from workflow_kit.approvals.service import overdue_approvals

    overdue = list(overdue_approvals())
    assert approval in overdue
    assert approval in list(overdue_approvals(workflow_name="p9_sla"))


def test_no_sla_means_never_overdue(parallel_workflow, invoice):
    workflow = parallel_workflow("p9_sla_none", None)
    execution = _started(workflow, invoice)
    approval = _step_approvals(execution)[0]
    assert approval.due_at is None
    assert approval.is_overdue is False


# --------------------------------------------------------------------------- #
# concurrency
# --------------------------------------------------------------------------- #


@pytest.mark.django_db(transaction=True)
def test_parallel_step_concurrent_decisions_stay_consistent(parallel_workflow, invoice):
    workflow = parallel_workflow(
        "p9_concurrent", ApprovalRequirement(approvers=["Manager", "Finance"])
    )
    execution = _started(workflow, invoice)
    execution.approve(_user("mgr_c", "Manager"))
    execution.approve(_user("fin_c", "Finance"))
    assert execution.current_state == "approved"

    stale = WorkflowExecution.objects.get(pk=execution.pk)
    with pytest.raises(WorkflowAlreadyCompletedError):
        stale.approve(_user("mgr_c2", "Manager"))

    fresh = WorkflowExecution.objects.get(pk=execution.pk)
    assert fresh.current_state == "approved"
    assert Approval.objects.filter(execution=fresh, status=ApprovalStatus.APPROVED).count() == 2
