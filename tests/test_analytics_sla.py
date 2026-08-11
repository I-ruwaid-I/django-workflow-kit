"""Phase 12 tests: SLA and escalation analytics.

Covers :func:`sla_metrics` compliance/breach/overdue statistics including the
pending-overdue and decided-late breach shapes, and :func:`escalation_analytics`
distribution breakdowns with the average escalation delay.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from workflow_kit.analytics import escalation_analytics, sla_metrics

from tests.analytics_helpers import manager, run, set_due_at
from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


def _invoice(number: str):
    return Invoice.objects.create(number=number, amount="100.00", vendor="Acme")


def test_sla_metrics_on_time_decisions(analytics_workflow, invoice):
    """On-time decisions yield full compliance and no breaches."""
    mgr = manager()
    execution = analytics_workflow.start(invoice)
    run(execution, "submit", user=mgr)
    set_due_at(execution, timezone.now() + timedelta(days=1))
    run(execution, "approve", user=mgr)

    metrics = sla_metrics(workflow="analytics_flow")
    assert metrics.tracked == 1
    assert metrics.decided == 1
    assert metrics.on_time == 1
    assert metrics.breached == 0
    assert metrics.pending_overdue == 0
    assert metrics.compliance_rate == pytest.approx(100.0)
    assert metrics.average_overdue is None


def test_sla_metrics_pending_overdue_breach(analytics_workflow, invoice):
    """Still-pending approvals past their deadline breach the SLA."""
    mgr = manager()
    execution = analytics_workflow.start(invoice)
    run(execution, "submit", user=mgr)
    set_due_at(execution, timezone.now() - timedelta(hours=2))

    metrics = sla_metrics(workflow="analytics_flow")
    assert metrics.tracked == 1
    assert metrics.decided == 0
    assert metrics.pending_overdue == 1
    assert metrics.breached == 1
    assert metrics.compliance_rate is None
    assert metrics.average_overdue is not None and 0 < metrics.average_overdue < 3 * 3600


def test_sla_metrics_late_decision_breach(analytics_workflow, invoice):
    """Deciding after the deadline is a breach too."""
    from workflow_kit.models import Approval

    mgr = manager()
    execution = analytics_workflow.start(invoice)
    run(execution, "submit", user=mgr)
    set_due_at(execution, timezone.now())
    run(execution, "approve", user=mgr)
    Approval.objects.filter(execution=execution).update(
        updated_at=timezone.now() + timedelta(minutes=10)
    )

    metrics = sla_metrics(workflow="analytics_flow")
    assert metrics.decided == 1
    assert metrics.on_time == 0
    assert metrics.breached == 1
    assert metrics.compliance_rate == pytest.approx(0.0)


def test_sla_metrics_shape_with_two_approvals(analytics_workflow, invoice):
    """Mixed on-time and overdue approvals compute compliance correctly."""
    mgr = manager()

    good = analytics_workflow.start(invoice)
    run(good, "submit", user=mgr)
    set_due_at(good, timezone.now() + timedelta(days=1))
    run(good, "approve", user=mgr)

    bad = analytics_workflow.start(_invoice("INV-2"))
    run(bad, "submit", user=mgr)
    set_due_at(bad, timezone.now() - timedelta(hours=1))

    metrics = sla_metrics(workflow="analytics_flow")
    assert metrics.tracked == 2
    assert metrics.decided == 1
    assert metrics.on_time == 1
    assert metrics.breached == 1
    assert metrics.compliance_rate == pytest.approx(100.0)
    assert metrics.average_overdue is not None


def test_escalation_analytics_breakdowns(analytics_workflow, invoice):
    """Escalation distribution by workflow, state, reason and delay."""
    mgr = manager()
    escalation_user = manager()
    execution = analytics_workflow.start(invoice)
    run(execution, "submit", user=mgr)
    execution.escalate(approver=escalation_user, user=mgr, reason="Finance input needed")

    rows = escalation_analytics(workflow="analytics_flow")
    assert rows["total"] == 1
    by_workflow = {row["key"]: row["count"] for row in rows["by_workflow"]}
    assert by_workflow["analytics_flow"] == 1
    by_state = {row["key"]: row["count"] for row in rows["by_state"]}
    assert by_state["review"] == 1
    by_reason = {row["key"]: row["count"] for row in rows["by_reason"]}
    assert by_reason["Finance input needed"] == 1
    assert rows["average_delay_seconds"] is not None


def test_escalation_analytics_empty(analytics_workflow, invoice):
    """No escalations produce a zero total and empty breakdowns."""
    analytics_workflow.start(invoice)
    rows = escalation_analytics(workflow="analytics_flow")
    assert rows["total"] == 0
    assert rows["by_workflow"] == []
    assert rows["by_state"] == []
    assert rows["by_reason"] == []
    assert rows["average_delay_seconds"] is None
