"""Phase 12 tests: execution and version metrics.

Covers the aggregate counts of :func:`execution_metrics` (started, active,
completed, rejected, cancelled, failed, escalated, SLA-breached), the filter
semantics (workflow, version, started-at range, current state), input
validation (bad dates, bad versions) and the per-version breakdown of
:func:`version_analytics`.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from workflow_kit.analytics import (
    AnalyticsError,
    ExecutionMetrics,
    execution_metrics,
    version_analytics,
)

from tests.analytics_helpers import manager, run, set_timestamps
from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


def _invoice(number: str, amount: str = "100.00"):
    return Invoice.objects.create(number=number, amount=amount, vendor="Acme")


def test_metrics_counts_every_outcome(analytics_workflow, invoice):
    """Started, active, completed, rejected, cancelled and failed counts."""
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)
    run(analytics_workflow.start(_invoice("INV-2")), "submit", user=mgr)
    run(analytics_workflow.start(_invoice("INV-3")), "submit", "reject", user=mgr)
    run(analytics_workflow.start(_invoice("INV-4")), "cancel", user=mgr)
    failed = analytics_workflow.start(_invoice("INV-5"))
    set_timestamps(failed, completed_at=timezone.now(), current_state="approved")

    metrics = execution_metrics()

    assert isinstance(metrics, ExecutionMetrics)
    assert metrics.started == 5
    assert metrics.active == 1
    assert metrics.completed == 1
    assert metrics.rejected == 1
    assert metrics.cancelled == 1
    assert metrics.failed == 1
    assert metrics.to_dict()["started"] == 5
    assert "5 started" in metrics.summary()


def test_metrics_scopes_by_workflow(analytics_workflow, invoice):
    """The ``workflow`` filter isolates a single workflow's executions."""
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)

    metrics = execution_metrics(workflow="analytics_flow")
    assert metrics.started == 1
    assert metrics.completed == 1

    metrics = execution_metrics(workflow="does_not_exist")
    assert metrics.started == 0


def test_metrics_scopes_by_started_at_range(analytics_workflow, invoice):
    """``start``/``end`` bound the execution set by ``started_at``."""
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)
    old = analytics_workflow.start(_invoice("INV-2"))
    set_timestamps(old, started_at=timezone.now() - timedelta(days=30))

    start = (timezone.now() - timedelta(days=1)).isoformat()
    metrics = execution_metrics(start=start)
    assert metrics.started == 1

    end = (timezone.now() - timedelta(days=1)).isoformat()
    metrics = execution_metrics(end=end)
    assert metrics.started == 1


def test_metrics_scopes_by_state(analytics_workflow, invoice):
    """``state`` keeps executions currently in that state."""
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", user=mgr)
    run(analytics_workflow.start(_invoice("INV-2")), "submit", "approve", user=mgr)

    metrics = execution_metrics(state="review")
    assert metrics.started == 1
    assert metrics.active == 1


def test_metrics_validation_errors(analytics_workflow, invoice):
    """Bad dates and non-integer versions raise :class:`AnalyticsError`."""
    analytics_workflow.start(invoice)
    with pytest.raises(AnalyticsError):
        execution_metrics(start="not-a-date")
    with pytest.raises(AnalyticsError):
        execution_metrics(workflow_version="abc")
    metrics = execution_metrics(start="2020-01-01", end="2019-01-01")
    assert metrics.started == 0


def test_metrics_count_escalated(analytics_workflow, invoice):
    """``escalated`` counts executions with an approval_escalated event."""
    mgr = manager()
    execution = run(analytics_workflow.start(invoice), "submit", user=mgr)
    other = manager()  # escalation approver needs the Manager group/resolver too
    execution.escalate(approver=other, user=mgr, reason="Needs finance input")

    assert execution_metrics(workflow="analytics_flow").escalated == 1


def test_metrics_sla_breached_via_overdue_pending(analytics_workflow, invoice):
    """Overdue-while-pending approvals mark executions as SLA-breached."""
    from tests.analytics_helpers import set_due_at

    mgr = manager()
    execution = run(analytics_workflow.start(invoice), "submit", user=mgr)
    set_due_at(execution, timezone.now() - timedelta(hours=1))

    assert execution_metrics(workflow="analytics_flow").sla_breached == 1


def test_metrics_sla_breached_via_late_decision(analytics_workflow, invoice):
    """Deciding after the deadline also marks the execution as breached."""
    from workflow_kit.models import Approval, WorkflowEvent

    from tests.analytics_helpers import set_due_at

    mgr = manager()
    execution = analytics_workflow.start(invoice)
    run(execution, "submit", user=mgr)
    set_due_at(execution, timezone.now())
    run(execution, "approve", user=mgr)
    late = timezone.now() + timedelta(minutes=30)
    WorkflowEvent.objects.filter(execution=execution, event_type="approval_approved").update(
        created_at=late
    )
    Approval.objects.filter(execution=execution).update(updated_at=late)

    assert execution_metrics(workflow="analytics_flow").sla_breached == 1


def test_version_analytics_reports_each_version(analytics_workflow, invoice):
    """Each persisted version is reported once with its own execution counts."""
    from workflow_kit.engine.versioning import ensure_workflow_version

    ensure_workflow_version(analytics_workflow, changelog="Initial")
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)

    rows = version_analytics(workflow="analytics_flow")
    assert len(rows) == 1
    row = rows[0]
    assert row.workflow == "analytics_flow"
    assert row.version == 1
    assert row.started == 1
    assert row.completed == 1
    assert row.published_at is not None


def test_version_analytics_empty_when_no_versions(analytics_workflow, invoice):
    """No persisted versions means no version rows."""
    analytics_workflow.start(invoice)
    assert version_analytics(workflow="analytics_flow") == []


def test_many_executions_stay_fast(analytics_workflow):
    """Metrics query cost must not scale with execution volume.

    The counts and the breach/outcome subqueries run on the database; only a
    constant number of queries should be issued regardless of the set size.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    mgr = manager()
    for number in range(150):
        run(
            analytics_workflow.start(_invoice(f"INV-B{number}")),
            "submit",
            "approve",
            user=mgr,
        )

    with CaptureQueriesContext(connection) as captured:
        metrics = execution_metrics()

    assert metrics.started == 150
    assert metrics.completed == 150
    assert len(captured) <= 12
