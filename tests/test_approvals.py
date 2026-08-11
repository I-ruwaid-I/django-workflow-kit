"""Phase 3 tests: the approval engine.

Covers approval-record creation as executions reach non-terminal states,
sequential approve/reject decisions through the authorization system,
persisted decision metadata, double-decision rejection and DB-level
consistency under concurrent decisions.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from workflow_kit import (
    ApprovalNotPendingError,
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


@pytest.fixture
def approval_workflow():
    workflow = Workflow(
        name="approval_workflow",
        initial="draft",
        states=["draft", "manager_review", "finance_review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "manager_review"),
            Transition("approve", "manager_review", "finance_review", permission=["Manager"]),
            Transition("approve", "finance_review", "approved", permission=["Finance"]),
            Transition("reject", "manager_review", "rejected", permission=["Manager"]),
        ],
    )
    yield workflow
    registry.unregister("approval_workflow")


@pytest.fixture
def single_step_workflow():
    workflow = Workflow(
        name="single_step_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission=["Manager"]),
            Transition("reject", "review", "rejected", permission=["Manager"]),
        ],
    )
    yield workflow
    registry.unregister("single_step_flow")


@pytest.fixture
def invoice():
    return Invoice.objects.create(number="INV-A1", vendor="Acme", amount="100.00")


def _user(username: str, *groups: str) -> get_user_model():
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={"password": "test-password-123"},
    )
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


def _manager():
    return _user("mgr", "Manager")


def _finance():
    return _user("fin", "Finance")


def _employee():
    return _user("emp", "Employee")


def _started(workflow, invoice) -> WorkflowExecution:
    execution = workflow.start(invoice)
    workflow.transition(execution, "submit")
    return execution


def _fresh_pending(execution, step: str) -> Approval:
    return Approval.objects.get(execution=execution, step=step, status=ApprovalStatus.PENDING)


# -- Approval records during transitions ---------------------------------------


def test_reaching_non_terminal_state_creates_pending_approval(approval_workflow, invoice):
    execution = approval_workflow.start(invoice)
    assert list(execution.pending_approvals()) == []

    approval_workflow.transition(execution, "submit")
    pending = list(execution.pending_approvals())
    assert len(pending) == 1
    assert pending[0].step == "manager_review"
    assert pending[0].status == ApprovalStatus.PENDING


def test_pending_approval_is_empty_in_initial_state(approval_workflow, invoice):
    execution = approval_workflow.start(invoice)
    assert list(execution.pending_approvals()) == []


# -- approve ------------------------------------------------------------------


def test_approve_resolves_approval_and_advances(approval_workflow, invoice):
    execution = _started(approval_workflow, invoice)
    manager = _manager()

    approval = execution.approve(manager)

    assert approval.step == "manager_review"
    assert approval.status == ApprovalStatus.APPROVED
    assert approval.approver == manager
    assert approval.action == "approve"
    assert [a.step for a in execution.pending_approvals()] == ["finance_review"]
    assert execution.current_state == "finance_review"


def test_sequential_approval_reaches_terminal_state(approval_workflow, invoice):
    execution = _started(approval_workflow, invoice)
    execution.approve(_manager())
    assert execution.current_state == "finance_review"

    next_pending = list(execution.pending_approvals())
    assert [a.step for a in next_pending] == ["finance_review"]

    finance_approval = execution.approve(_finance())
    assert finance_approval.status == ApprovalStatus.APPROVED
    assert execution.current_state == "approved"
    assert execution.is_completed is True
    assert list(execution.pending_approvals()) == []


def test_full_approval_history_is_recorded(approval_workflow, invoice):
    execution = _started(approval_workflow, invoice)
    execution.approve(_manager())
    execution.approve(_finance())
    approvals = list(execution.approvals.order_by("created_at", "id"))
    assert [a.step for a in approvals] == ["manager_review", "finance_review"]
    assert [a.status for a in approvals] == [ApprovalStatus.APPROVED, ApprovalStatus.APPROVED]


def test_approve_with_reason_is_persisted(approval_workflow, invoice):
    execution = _started(approval_workflow, invoice)
    approval = execution.approve(_manager(), reason="all good")
    approval.refresh_from_db()
    assert approval.reason == "all good"
    assert approval.approver is not None


def test_approve_execution_service_matches_model_api(approval_workflow, invoice):
    from workflow_kit.approvals.service import approve_execution

    execution = _started(approval_workflow, invoice)
    result = approve_execution(execution, user=_manager())
    assert result.status == ApprovalStatus.APPROVED
    assert execution.current_state == "finance_review"


# -- reject -------------------------------------------------------------------


def test_reject_moves_to_rejected_state(approval_workflow, invoice):
    execution = _started(approval_workflow, invoice)
    approval = execution.reject(_manager(), reason="missing quotation")

    assert approval.status == ApprovalStatus.REJECTED
    assert approval.reason == "missing quotation"
    assert execution.current_state == "rejected"
    assert execution.is_completed is True
    assert list(execution.pending_approvals()) == []


def test_approval_after_reject_raises_completed(approval_workflow, invoice):
    execution = _started(approval_workflow, invoice)
    execution.reject(_manager(), reason="nope")
    with pytest.raises(WorkflowAlreadyCompletedError):
        execution.approve(_manager())


# -- authorization ------------------------------------------------------------


def test_unauthorized_user_cannot_approve(approval_workflow, invoice):
    execution = _started(approval_workflow, invoice)
    with pytest.raises(PermissionDeniedError):
        execution.approve(_employee())
    approval = _fresh_pending(execution, "manager_review")
    assert approval.approver is None
    assert WorkflowExecution.objects.get(pk=execution.pk).current_state == "manager_review"


def test_unauthorized_user_cannot_reject(approval_workflow, invoice):
    execution = _started(approval_workflow, invoice)
    with pytest.raises(PermissionDeniedError):
        execution.reject(_employee(), reason="nope")
    assert execution.current_state == "manager_review"
    assert _fresh_pending(execution, "manager_review").status == ApprovalStatus.PENDING


def test_approval_permission_is_scoped_to_state(approval_workflow, invoice):
    execution = _started(approval_workflow, invoice)
    finance = _finance()
    with pytest.raises(PermissionDeniedError):
        execution.approve(finance)

    execution.approve(_manager())
    assert execution.current_state == "finance_review"

    manager = _manager()
    with pytest.raises(PermissionDeniedError):
        execution.approve(manager)
    execution.approve(finance)
    assert execution.current_state == "approved"


def test_no_pending_approval_raises(approval_workflow, invoice):
    execution = _started(approval_workflow, invoice)
    Approval.objects.filter(execution=execution, status=ApprovalStatus.PENDING).delete()
    with pytest.raises(ApprovalNotPendingError):
        execution.approve(_manager())
    assert WorkflowExecution.objects.get(pk=execution.pk).current_state == "manager_review"


# -- repeated decisions -------------------------------------------------------


def test_approving_twice_second_call_raises(single_step_workflow, invoice):
    execution = _started(single_step_workflow, invoice)
    manager = _manager()
    first = execution.approve(manager)
    assert first.status == ApprovalStatus.APPROVED
    with pytest.raises(WorkflowAlreadyCompletedError):
        execution.approve(manager)
    assert Approval.objects.filter(execution=execution, status=ApprovalStatus.APPROVED).count() == 1


def test_only_first_reject_wins(single_step_workflow, invoice):
    execution = _started(single_step_workflow, invoice)
    manager = _manager()
    execution.reject(manager, reason="first")
    with pytest.raises(WorkflowAlreadyCompletedError):
        execution.reject(manager, reason="second")
    approval = execution.approvals.get(step="review")
    assert approval.status == ApprovalStatus.REJECTED
    assert approval.reason == "first"


# -- concurrency --------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_racing_decisions_leave_one_consistent_winner(single_step_workflow, invoice):
    """A lost-update scenario must never double-advance an execution.

    The engine re-reads and locks the execution row inside the decision, so a
    second caller holding a stale snapshot is refused rather than silently
    double-approving the same step.
    """
    execution = _started(single_step_workflow, invoice)
    manager = _manager()

    first = execution.approve(manager)
    assert first.status == ApprovalStatus.APPROVED

    stale = WorkflowExecution.objects.get(pk=execution.pk)
    with pytest.raises(WorkflowAlreadyCompletedError):
        stale.approve(manager)

    fresh = WorkflowExecution.objects.get(pk=execution.pk)
    assert fresh.current_state == "approved"
    assert fresh.is_completed is True
    assert Approval.objects.filter(execution=stale, status=ApprovalStatus.APPROVED).count() == 1


# -- transactionality ---------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_approve_rolls_back_on_effect_failure(approval_workflow, invoice):
    execution = _started(approval_workflow, invoice)
    with (
        patch(
            "workflow_kit.approvals.service.apply_transition",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(RuntimeError),
    ):
        execution.approve(_manager())

    fresh = WorkflowExecution.objects.get(pk=execution.pk)
    assert fresh.current_state == "manager_review"
    approval = fresh.pending_approvals().get(step="manager_review")
    assert approval.status == ApprovalStatus.PENDING
    assert approval.approver is None


@pytest.mark.django_db(transaction=True)
def test_reject_rolls_back_on_effect_failure(approval_workflow, invoice):
    execution = _started(approval_workflow, invoice)
    with (
        patch(
            "workflow_kit.approvals.service.apply_transition",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(RuntimeError),
    ):
        execution.reject(_manager(), reason="nope")
    fresh = WorkflowExecution.objects.get(pk=execution.pk)
    assert fresh.current_state == "manager_review"
    assert fresh.pending_approvals().get(step="manager_review").status == ApprovalStatus.PENDING
