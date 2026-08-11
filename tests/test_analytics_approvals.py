"""Phase 12 tests: approval analytics.

Covers the aggregate counts and decision-time statistics of
:func:`approval_metrics`, the grouped ``approval_totals`` breakdowns, the
approval-scoped filter semantics and input validation.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from workflow_kit.analytics import (
    AnalyticsError,
    ApprovalMetrics,
    approval_metrics,
    approval_totals,
)

from tests.analytics_helpers import manager, retime_events, run, set_timestamps
from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


def _invoice(number: str):
    return Invoice.objects.create(number=number, amount="100.00", vendor="Acme")


def test_approval_metrics_counts(analytics_workflow, invoice):
    """Requested/approved/rejected/pending/cancelled counts over one step."""
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)
    run(analytics_workflow.start(_invoice("INV-2")), "submit", "reject", user=mgr)
    run(analytics_workflow.start(_invoice("INV-3")), "submit", user=mgr)  # pending

    metrics = approval_metrics(workflow="analytics_flow")
    assert isinstance(metrics, ApprovalMetrics)
    assert metrics.requested == 3
    assert metrics.approved == 1
    assert metrics.rejected == 1
    assert metrics.pending == 1
    assert metrics.cancelled == 0

    assert metrics.to_dict()["pending"] == 1


def test_approval_metrics_decision_durations(analytics_workflow, invoice):
    """Approved/rejected decision-time stats match the pinned timestamps."""
    mgr = manager()

    approved = analytics_workflow.start(invoice)
    run(approved, "submit", user=mgr)
    then = timezone.now() - timedelta(minutes=10)
    retime_events(approved, {("transition_executed", "submit"): then})
    run(approved, "approve", user=mgr)
    set_timestamps(approved, started_at=then - timedelta(minutes=5))

    rejected = analytics_workflow.start(_invoice("INV-2"))
    run(rejected, "submit", "reject", user=mgr)

    metrics = approval_metrics(workflow="analytics_flow")
    assert metrics.approved_duration.count == 1
    assert metrics.rejected_duration.count == 1


def test_approval_metrics_scopes_by_step_and_version(analytics_workflow, invoice):
    """``state`` filters by the approval step name."""
    from workflow_kit.engine.versioning import ensure_workflow_version

    ensure_workflow_version(analytics_workflow, changelog="Initial")
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)

    assert approval_metrics(workflow="analytics_flow", state="review").requested == 1
    assert approval_metrics(workflow="analytics_flow", state="draft").requested == 0
    assert approval_metrics(workflow="analytics_flow", workflow_version="1").requested == 1
    assert approval_metrics(workflow="analytics_flow", workflow_version="999").requested == 0


def test_approval_totals_grouped_by_status(analytics_workflow, invoice):
    """``group_by="status"`` returns one row per approval status."""
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)
    run(analytics_workflow.start(_invoice("INV-2")), "submit", user=mgr)

    rows = approval_totals(workflow="analytics_flow", group_by="status")
    by_status = {row["status"]: row for row in rows}
    assert by_status["APPROVED"]["approved"] == 1
    assert by_status["PENDING"]["pending"] == 1
    assert by_status["APPROVED"]["requested"] == 1
    assert by_status["PENDING"]["requested"] == 1


def test_approval_totals_grouped_by_workflow(analytics_workflow, invoice):
    """The default ``group_by="workflow"`` groups by the workflow name."""
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)

    rows = approval_totals()
    by_workflow = {row["workflow"]: row for row in rows}
    assert by_workflow["analytics_flow"]["approved"] == 1


def test_approval_totals_rejects_unknown_grouping(analytics_workflow, invoice):
    """An unsupported ``group_by`` value raises :class:`AnalyticsError`."""
    analytics_workflow.start(invoice)
    with pytest.raises(AnalyticsError):
        approval_totals(group_by="who")


def test_approval_metrics_rejects_bad_version(analytics_workflow, invoice):
    """A non-integer version raises :class:`AnalyticsError`."""
    analytics_workflow.start(invoice)
    with pytest.raises(AnalyticsError):
        approval_metrics(workflow_version="abc")
