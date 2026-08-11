"""Workflow tests for the Invoice approval demo.

These exercise the workflow engine through the demo's service layer, the same
way a real Django application would use the package. Every action is performed
by a real user, so authorization (groups and permissions) is enforced
end-to-end by the engine, not only by the UI.
"""

import pytest
from workflow_kit import (
    InvalidTransitionError,
    PermissionDeniedError,
    WorkflowAlreadyCompletedError,
)

from invoices.services import (
    approve_invoice,
    create_invoice,
    invoice_execution_version,
    publish_invoice_v2,
    reject_invoice,
    submit_invoice,
)

pytestmark = pytest.mark.django_db


def _new_invoice(number: str):
    return create_invoice(number=number, customer_name="Acme", amount="500.00")


def _submit(invoice, demo_users):
    submit_invoice(invoice, user=demo_users["employee"])
    return invoice


def test_happy_path_to_approved(demo_users):
    invoice = _new_invoice("INV-HAPPY")
    assert invoice.current_state == "draft"
    assert not invoice.available_actions()
    assert set(invoice.available_actions(demo_users["employee"])) == {"submit"}

    _submit(invoice, demo_users)
    assert invoice.current_state == "manager_review"
    assert not invoice.available_actions(demo_users["employee"])
    assert set(invoice.available_actions(demo_users["manager"])) == {"approve", "reject"}

    approve_invoice(invoice, user=demo_users["manager"])
    assert invoice.current_state == "finance_review"
    assert set(invoice.available_actions(demo_users["finance"])) == {"approve", "reject"}
    assert invoice.available_actions(demo_users["manager"]) == ["reject"]

    approve_invoice(invoice, user=demo_users["finance"])
    assert invoice.current_state == "approved"
    assert invoice.current_state_label == "Approved"
    assert invoice.execution.is_completed is True
    assert invoice.available_actions(demo_users["finance"]) == []


def test_rejection_at_manager_review(demo_users):
    invoice = _new_invoice("INV-REJ1")
    _submit(invoice, demo_users)
    reject_invoice(invoice, user=demo_users["manager"])
    assert invoice.current_state == "rejected"
    assert invoice.execution.is_completed is True


def test_rejection_at_finance_review(demo_users):
    invoice = _new_invoice("INV-REJ2")
    _submit(invoice, demo_users)
    approve_invoice(invoice, user=demo_users["manager"])
    assert invoice.current_state == "finance_review"
    reject_invoice(invoice, user=demo_users["finance"])
    assert invoice.current_state == "rejected"


def test_manager_can_reject_but_not_finalize_finance_stage(demo_users):
    """Manager has ``can_reject_invoice`` but not ``can_finalize_invoice``."""
    invoice = _new_invoice("INV-FINR")
    _submit(invoice, demo_users)
    approve_invoice(invoice, user=demo_users["manager"])
    assert invoice.current_state == "finance_review"

    with pytest.raises(PermissionDeniedError):
        approve_invoice(invoice, user=demo_users["manager"])
    assert invoice.current_state == "finance_review"

    reject_invoice(invoice, user=demo_users["manager"])
    assert invoice.current_state == "rejected"


def test_employee_cannot_approve_as_manager(demo_users):
    invoice = _submit(_new_invoice("INV-SERM"), demo_users)
    with pytest.raises(PermissionDeniedError):
        approve_invoice(invoice, user=demo_users["employee"])
    assert invoice.current_state == "manager_review"

    fresh = invoice.execution.__class__.objects.get(pk=invoice.execution.pk)
    assert fresh.current_state == "manager_review"


def test_invalid_action_from_draft(demo_users):
    invoice = _new_invoice("INV-BAD")
    with pytest.raises(InvalidTransitionError):
        approve_invoice(invoice, user=demo_users["manager"])
    assert invoice.current_state == "draft"


def test_completed_workflow_cannot_transition(demo_users):
    invoice = _new_invoice("INV-DONE")
    _submit(invoice, demo_users)
    approve_invoice(invoice, user=demo_users["manager"])
    approve_invoice(invoice, user=demo_users["finance"])
    assert invoice.current_state == "approved"
    with pytest.raises(WorkflowAlreadyCompletedError):
        approve_invoice(invoice, user=demo_users["finance"])
    assert invoice.current_state == "approved"


def test_can_transition_reflects_definition_and_user(demo_users):
    invoice = _new_invoice("INV-CAN")
    assert invoice.execution.can_transition("submit", demo_users["employee"]) is True
    assert invoice.execution.can_transition("submit") is False
    assert invoice.execution.can_transition("approve", demo_users["manager"]) is False
    _submit(invoice, demo_users)
    assert invoice.execution.can_transition("approve", demo_users["manager"]) is True
    assert invoice.execution.can_transition("approve", demo_users["employee"]) is False
    assert invoice.execution.can_transition("submit", demo_users["employee"]) is False


def test_anonymous_user_denied(demo_users):
    invoice = _new_invoice("INV-ANON")
    _submit(invoice, demo_users)
    with pytest.raises(PermissionDeniedError):
        approve_invoice(invoice, user=None)
    assert invoice.current_state == "manager_review"


def test_approval_decisions_create_approval_records(demo_users):
    invoice = _submit(_new_invoice("INV-APPR"), demo_users)
    approvals = list(invoice.execution.approvals.order_by("created_at"))
    assert len(approvals) == 1
    assert approvals[0].step == "manager_review"

    approve_invoice(invoice, user=demo_users["manager"])
    decisions = {a.step: a.status for a in invoice.execution.approvals.all()}
    assert decisions["manager_review"] == "APPROVED"
    assert invoice.current_state == "finance_review"


def test_reject_reason_is_persisted_and_timeline_visible(demo_users):
    invoice = _submit(_new_invoice("INV-REJ"), demo_users)
    reject_invoice(invoice, user=demo_users["manager"], reason="Duplicate invoice")

    approval = invoice.execution.approvals.get(step="manager_review")
    assert approval.status == "REJECTED"
    assert approval.reason == "Duplicate invoice"

    timeline = invoice.execution.timeline()
    rejected = next(e for e in timeline if e.event_type == "approval_rejected")
    assert rejected.reason == "Duplicate invoice"
    assert rejected.actor == "manager"


def test_timeline_derives_from_audit_events(demo_users):
    invoice = _submit(_new_invoice("INV-TIM"), demo_users)
    approve_invoice(invoice, user=demo_users["manager"])
    approve_invoice(invoice, user=demo_users["finance"])

    labels = [e.label for e in invoice.execution.timeline()]
    assert labels == [
        "Workflow started",
        "State changed",
        "Approval required",
        "Approved",
        "State changed",
        "Approval required",
        "Approved",
        "State changed",
        "Workflow completed",
    ]


def test_large_invoice_routed_to_executive_review(demo_users):
    """Invoices above the threshold get an extra parallel approval step."""
    invoice = create_invoice(
        number="INV-LARGE",
        customer_name="Acme",
        amount="10_500.00",
    )
    assert invoice.current_state == "draft"
    _submit(invoice, demo_users)

    approve_invoice(invoice, user=demo_users["manager"])
    assert invoice.current_state == "finance_review"

    approve_invoice(invoice, user=demo_users["finance"])
    assert invoice.current_state == "executive_review"
    assert invoice.current_state_label == "Executive Review"
    assert set(invoice.available_actions(demo_users["finance"])) == {"approve", "reject"}

    # Executive review is a parallel all-of step: both Finance and Executive
    # must approve before the invoice can be finalized.
    approve_invoice(invoice, user=demo_users["finance"])
    assert invoice.current_state == "executive_review"

    approve_invoice(invoice, user=demo_users["executive"])
    assert invoice.current_state == "approved"
    assert invoice.execution.is_completed is True


def test_at_threshold_amount_finalized_directly(demo_users):
    """Amount <= 10_000 finalizes directly from finance review."""
    invoice = create_invoice(
        number="INV-THRESHOLD",
        customer_name="Acme",
        amount="10_000.00",
    )
    _submit(invoice, demo_users)
    approve_invoice(invoice, user=demo_users["manager"])
    assert invoice.current_state == "finance_review"

    approve_invoice(invoice, user=demo_users["finance"])
    assert invoice.current_state == "approved"
    assert invoice.execution.is_completed is True


def test_executions_are_pinned_to_a_published_version(demo_users):
    """Every demo execution binds to the published version 1 snapshot."""
    invoice = _new_invoice("INV-VER1")
    assert invoice_execution_version(invoice) == 1


def test_publishing_v2_keeps_running_executions_on_v1(demo_users):
    """New executions bind to v2; already-running invoices keep v1 routing."""
    old = create_invoice(number="INV-V2OLD", customer_name="Acme", amount="15_000.00")
    _submit(old, demo_users)
    approve_invoice(old, user=demo_users["manager"])
    assert old.current_state == "finance_review"
    assert invoice_execution_version(old) == 1

    publish_invoice_v2()

    new = create_invoice(number="INV-V2NEW", customer_name="Acme", amount="15_000.00")
    assert invoice_execution_version(new) == 2

    # v1 threshold is 10_000: this 15_000 invoice re-routes to Executive Review
    # because it is bound to version 1, even though version 2 (threshold 25_000)
    # would finalize it directly.
    approve_invoice(old, user=demo_users["finance"])
    assert old.current_state == "executive_review"

    # v2 threshold is 25_000: identical amount finalizes directly.
    _submit(new, demo_users)
    approve_invoice(new, user=demo_users["manager"])
    approve_invoice(new, user=demo_users["finance"])
    assert new.current_state == "approved"
    assert new.execution.is_completed is True
