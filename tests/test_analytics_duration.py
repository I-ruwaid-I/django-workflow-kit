"""Phase 12 tests: completion times, state durations and bottlenecks.

``completion_metrics`` derives ``completed_at - started_at``; ``state_durations``
reconstructs per-state spans from the audit trail; ``bottlenecks`` flags the
states whose average easily exceeds the rest. Timestamps are pinned so the
assertions are deterministic.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from workflow_kit.analytics import (
    AnalyticsError,
    CompletionMetrics,
    StateDuration,
    bottlenecks,
    completion_metrics,
    state_durations,
)

from tests.analytics_helpers import manager, retime_events, run, set_timestamps
from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


def _invoice(number: str):
    return Invoice.objects.create(number=number, amount="100.00", vendor="Acme")


def test_completion_metrics_durations(analytics_workflow, invoice):
    """Counts, completed count and exact average/median/min/max over seconds."""
    mgr = manager()
    first = analytics_workflow.start(invoice)
    second = analytics_workflow.start(_invoice("INV-2"))
    run(analytics_workflow.start(_invoice("INV-3")), "submit", user=mgr)  # still open

    set_timestamps(first, started_at=timezone.now() - timedelta(minutes=10))
    run(first, "submit", "approve", user=mgr)
    set_timestamps(first, completed_at=timezone.now() - timedelta(minutes=8))

    set_timestamps(second, started_at=timezone.now() - timedelta(minutes=30))
    run(second, "submit", "approve", user=mgr)
    set_timestamps(second, completed_at=timezone.now() - timedelta(minutes=20))

    metrics = completion_metrics(workflow="analytics_flow")
    assert isinstance(metrics, CompletionMetrics)
    assert metrics.total == 3
    assert metrics.completed == 2
    duration = metrics.duration
    assert duration.count == 2
    assert duration.average == pytest.approx(360.0, abs=2.0)
    assert duration.median == pytest.approx(360.0, abs=2.0)
    assert duration.minimum == pytest.approx(120.0, abs=2.0)
    assert duration.maximum == pytest.approx(600.0, abs=2.0)
    assert metrics.to_dict()["completed"] == 2


def test_completion_metrics_empty(analytics_workflow):
    """Empty sets produce zero counts with ``None`` aggregate stats."""
    metrics = completion_metrics(workflow="analytics_flow")
    assert metrics.total == 0
    assert metrics.completed == 0
    assert metrics.duration.count == 0
    assert metrics.duration.average is None
    assert metrics.duration.p99 is None


def test_state_durations_from_audit_trail(analytics_workflow, invoice):
    """Per-state spans match the pinned event timestamps."""
    from workflow_kit.models import WorkflowEvent

    mgr = manager()
    execution = analytics_workflow.start(invoice)
    started = timezone.now() - timedelta(hours=2)
    set_timestamps(execution, started_at=started)

    submit_at = started + timedelta(minutes=10)
    run(execution, "submit", user=mgr)
    approve_at = submit_at + timedelta(minutes=20)
    run(execution, "approve", user=mgr)
    completed_at = approve_at + timedelta(minutes=30)
    set_timestamps(execution, completed_at=completed_at)
    retime_events(
        execution,
        {
            ("transition_executed", "submit"): submit_at,
            ("transition_executed", "approve"): approve_at,
        },
    )
    WorkflowEvent.objects.filter(execution=execution, event_type="workflow_started").update(
        created_at=started
    )

    rows = {row.state: row for row in state_durations(workflow="analytics_flow")}
    # draft: started_at -> first transition (submit, +10 min)
    assert rows["draft"].duration.average == pytest.approx(600.0)
    # review: submit -> approve (20 min)
    assert rows["review"].duration.average == pytest.approx(1200.0)
    # approved: approve -> completed_at (+30 min)
    assert rows["approved"].duration.average == pytest.approx(1800.0)


def test_state_durations_open_execution_uses_now(analytics_workflow, invoice):
    """A running execution's last state span extends to "now"."""
    mgr = manager()
    execution = analytics_workflow.start(invoice)
    started = timezone.now() - timedelta(minutes=5)
    set_timestamps(execution, started_at=started)
    run(execution, "submit", user=mgr)

    rows = {row.state: row for row in state_durations(workflow="analytics_flow")}
    draft = rows["draft"].duration.average
    review = rows["review"].duration.average
    assert draft is not None and draft >= 0
    assert review is not None and review <= 600.0  # bounded by "now - started"


def test_state_durations_no_transitions(analytics_workflow, invoice):
    """An execution that never moved spends its whole life in the initial state."""
    execution = analytics_workflow.start(invoice)
    set_timestamps(execution, started_at=timezone.now() - timedelta(days=1))

    rows = state_durations(workflow="analytics_flow")
    assert len(rows) == 1
    assert rows[0].state == "draft"
    assert rows[0].count == 1
    assert not rows[0].is_bottleneck


def test_bottlenecks_flags_slow_state(analytics_workflow, invoice):
    """The slowest state is flagged as a bottleneck and rows rank by average."""
    mgr = manager()
    now = timezone.now()
    started = now - timedelta(minutes=40)
    submit_at = now - timedelta(minutes=30)
    approve_at = now - timedelta(minutes=5)
    for index in range(6):
        execution = analytics_workflow.start(_invoice(f"INV-B{index}"))
        set_timestamps(execution, started_at=started)
        run(execution, "submit", user=mgr)
        retime_events(
            execution,
            {
                ("transition_executed", "submit"): submit_at,
                ("transition_executed", "approve"): approve_at,
            },
        )
        run(execution, "approve", user=mgr)
        set_timestamps(execution, completed_at=now)

    rows = bottlenecks(workflow="analytics_flow")
    assert all(isinstance(row, StateDuration) for row in rows)
    flagged = [row for row in rows if row.is_bottleneck]
    assert flagged
    assert any(row.state == "review" for row in flagged)
    averages = [row.duration.average for row in rows]
    assert averages == sorted(averages, reverse=True)


def test_bottlenecks_requires_positive_threshold(analytics_workflow, invoice):
    """A non-positive threshold is rejected."""
    analytics_workflow.start(invoice)
    with pytest.raises(AnalyticsError):
        bottlenecks(threshold=0)
