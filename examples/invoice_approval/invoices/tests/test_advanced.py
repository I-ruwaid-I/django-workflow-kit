"""Phase 9 advanced workflow tests for the Invoice Approval demo.

These exercise parallel (all-of) approvals, delegation and escalation through
the demo's service layer, end-to-end with real users so Django authorization
(groups and permissions) is enforced just like in production.
"""

import pytest
from workflow_kit import ApprovalNotPendingError, PermissionDeniedError

from invoices.services import (
    approve_invoice,
    create_invoice,
    delegate_invoice,
    escalate_invoice,
    submit_invoice,
)

pytestmark = pytest.mark.django_db


def _new_large_invoice(number: str, demo_users):
    invoice = create_invoice(number=number, customer_name="Acme", amount="10_500.00")
    submit_invoice(invoice, user=demo_users["employee"])
    return invoice


def _to_executive_review(number: str, demo_users):
    invoice = _new_large_invoice(number, demo_users)
    approve_invoice(invoice, user=demo_users["manager"])
    approve_invoice(invoice, user=demo_users["finance"])
    return invoice


def test_parallel_all_step_creates_one_approval_per_slot(demo_users):
    invoice = _to_executive_review("ADV-EXEC", demo_users)
    assert invoice.current_state == "executive_review"

    pending = list(invoice.execution.pending_approvals())
    assert len(pending) == 2
    assert {a.mode for a in pending} == {"ALL"}
    assignments = {a.assignment["name"] for a in pending}
    assert assignments == {"Executive", "Finance"}


def test_parallel_all_partial_approval_keeps_execution_pending(demo_users):
    invoice = _to_executive_review("ADV-PART", demo_users)
    approve_invoice(invoice, user=demo_users["finance"])
    assert invoice.current_state == "executive_review"

    decided = {a.status for a in invoice.execution.approvals.all()}
    assert decided == {"APPROVED", "PENDING"}


def test_parallel_all_user_cannot_decide_the_same_slot_twice(demo_users):
    invoice = _to_executive_review("ADV-TWICE", demo_users)
    approve_invoice(invoice, user=demo_users["finance"])
    with pytest.raises(ApprovalNotPendingError):
        approve_invoice(invoice, user=demo_users["finance"])
    assert invoice.current_state == "executive_review"
    assert invoice.execution.is_completed is False


def test_parallel_all_completes_only_after_all_decide(demo_users):
    invoice = _to_executive_review("ADV-BOTH", demo_users)
    approve_invoice(invoice, user=demo_users["finance"])
    approve_invoice(invoice, user=demo_users["executive"])
    assert invoice.current_state == "approved"
    assert invoice.execution.is_completed is True


def test_delegated_user_can_decide_on_granters_behalf(demo_users):
    invoice = _to_executive_review("ADV-DEL", demo_users)

    # Executive review is a parallel all-of step: the Executive slot is granted
    # to the employee, who is not a member of the Executive group, so the
    # approval is only possible through the delegation. The engine authorizes
    # the decision against the granter's (executive) rights.
    delegate_invoice(
        invoice,
        granter=demo_users["executive"],
        grantee=demo_users["employee"],
        step="executive_review",
        reason="Executive on leave",
    )
    approve_invoice(invoice, user=demo_users["employee"])
    assert invoice.current_state == "executive_review"

    approve_invoice(invoice, user=demo_users["finance"])
    assert invoice.current_state == "approved"
    assert invoice.execution.is_completed is True


def test_escalation_replaces_pending_slots_with_single_approver(demo_users):
    invoice = create_invoice(number="ADV-ESC", customer_name="Acme", amount="500.00")
    submit_invoice(invoice, user=demo_users["employee"])
    approve_invoice(invoice, user=demo_users["manager"])
    assert invoice.current_state == "finance_review"

    escalate_invoice(
        invoice,
        approver="Executive",
        user=demo_users["finance"],
        reason="Urgent override",
    )
    pending = list(invoice.execution.pending_approvals())
    assert len(pending) == 1
    assert pending[0].step == "finance_review"
    assert pending[0].assignment["name"] == "Executive"
    assert pending[0].assignment["escalated"] is True

    approve_invoice(invoice, user=demo_users["executive"])
    assert invoice.current_state == "approved"
    assert invoice.execution.is_completed is True


def test_escalation_requires_authorized_actor(demo_users):
    invoice = _new_large_invoice("ADV-ESCA", demo_users)

    with pytest.raises(PermissionDeniedError):
        escalate_invoice(
            invoice,
            approver="Executive",
            user=demo_users["employee"],
            reason="No authority",
        )
    assert invoice.current_state == "manager_review"
