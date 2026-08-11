"""Duration analytics: how long workflows take (Phase 12).

``completion_metrics`` answers "how long is it taking?" with count, average,
median, minimum, maximum, P95 and P99 completion times. ``state_durations``
reconstructs -- from the ``started_at`` timestamp, the ordered
``transition_executed`` audit events and ``completed_at`` -- how long
executions spend in each state, which feeds ``bottlenecks``.

Averages, medians and percentiles require the durations themselves, so those
metrics materialise only the two or three timestamp columns of the filtered
set (never whole ``WorkflowExecution`` rows); counts stay on the database side.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.utils import timezone

from workflow_kit.analytics.base import (
    DurationStats,
    execution_queryset,
    parse_int,
)

_TOLERANCE_SECONDS = 1e-6


@dataclass(frozen=True)
class CompletionMetrics:
    """Completion times over a filtered set of executions."""

    total: int
    completed: int
    duration: DurationStats

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary of the completion metrics."""
        return {
            "total": self.total,
            "completed": self.completed,
            "duration": self.duration.to_dict(),
        }


def completion_metrics(
    *,
    workflow: str | None = None,
    workflow_version: int | str | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    state: str | None = None,
) -> CompletionMetrics:
    """Return completion-time statistics for executions matching the filters.

    ``total`` counts every execution in scope; ``completed`` the finished ones;
    ``duration`` summarises the ``completed_at - started_at`` times of the
    completed executions (seconds).
    """
    scope = execution_queryset(
        workflow=workflow,
        workflow_version=parse_int(workflow_version, name="workflow_version"),
        start=start,
        end=end,
        state=state,
    )
    total = scope.count()
    completed_scope = scope.filter(completed_at__isnull=False)
    completed = completed_scope.count()
    durations: list[float] = []
    for start_at, end_at in completed_scope.values_list("started_at", "completed_at"):
        if start_at is not None and end_at is not None:
            durations.append((end_at - start_at).total_seconds())
    return CompletionMetrics(
        total=total,
        completed=completed,
        duration=DurationStats.from_seconds(durations),
    )


@dataclass(frozen=True)
class StateDuration:
    """Duration statistics for the time executions spend in one state.

    ``is_bottleneck`` is only meaningful on rows returned by
    :func:`bottlenecks`; everywhere else it stays ``False``.
    """

    state: str
    count: int
    duration: DurationStats
    is_bottleneck: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary of this state's durations."""
        return {
            "state": self.state,
            "count": self.count,
            "is_bottleneck": self.is_bottleneck,
            **self.duration.to_dict(),
        }


def state_durations(
    *,
    workflow: str | None = None,
    workflow_version: int | str | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
) -> list[StateDuration]:
    """Return how long executions spend in each state, newest-to-oldest by count.

    Spans are derived from audit data only: an execution is in its initial
    state from ``started_at`` until its first transition, and in each later
    state between consecutive transitions, ending at ``completed_at`` (or "now"
    for running executions).
    """
    scope = execution_queryset(
        workflow=workflow,
        workflow_version=parse_int(workflow_version, name="workflow_version"),
        start=start,
        end=end,
    )
    executions = list(scope.values_list("id", "started_at", "completed_at", "current_state"))
    events = _transition_events([row[0] for row in executions])

    now = timezone.now()
    spans: dict[str, list[float]] = {}
    for execution_id, started_at, completed_at, current_state in executions:
        end_at = completed_at if completed_at is not None else now
        by_execution = events.get(execution_id, [])
        entries: list[tuple[datetime, str]] = []
        if by_execution:
            entries.append((started_at, by_execution[0]["source_state"]))
            entries.extend((item["created_at"], item["target_state"]) for item in by_execution)
        else:
            entries.append((started_at, current_state))
        for index, (entry_at, state) in enumerate(entries):
            exit_at = entries[index + 1][0] if index + 1 < len(entries) else end_at
            seconds = (exit_at - entry_at).total_seconds()
            if seconds > _TOLERANCE_SECONDS:
                spans.setdefault(state, []).append(seconds)

    rows = [
        StateDuration(state=state, count=len(values), duration=DurationStats.from_seconds(values))
        for state, values in spans.items()
    ]
    return sorted(rows, key=lambda row: row.count, reverse=True)


def _transition_events(execution_ids: list[int]) -> dict[int, list[Any]]:
    """Map execution ids to their ordered ``transition_executed`` audit events."""
    from workflow_kit.models.history import WorkflowEvent, WorkflowEventType

    grouped: dict[int, list[Any]] = {}
    if not execution_ids:
        return grouped
    events = (
        WorkflowEvent.objects.filter(
            execution_id__in=execution_ids,
            event_type=WorkflowEventType.TRANSITION_EXECUTED,
        )
        .order_by("execution_id", "created_at", "id")
        .values("execution_id", "source_state", "target_state", "created_at")
    )
    for event in events:
        grouped.setdefault(event["execution_id"], []).append(event)
    return grouped


def bottlenecks(
    *,
    workflow: str | None = None,
    workflow_version: int | str | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    threshold: float = 1.25,
) -> list[StateDuration]:
    """Rank states by average time consumed, flagging disproportionate ones.

    A state is flagged ``is_bottleneck`` when its average duration exceeds the
    overall average (across all state spans) by ``threshold`` times. Rows are
    ordered by average duration descending. This identifies *where* workflows
    stall, without claiming a causal explanation.
    """
    if threshold <= 0:
        from workflow_kit.analytics.base import AnalyticsError

        raise AnalyticsError("bottleneck threshold must be a positive number.")
    rows = state_durations(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
    )
    averages = [row.duration.average for row in rows if row.duration.average is not None]
    if not averages:
        return []
    overall = sum(averages) / len(averages)
    ranked = sorted(
        rows,
        key=lambda row: row.duration.average if row.duration.average is not None else 0.0,
        reverse=True,
    )
    flagged: list[StateDuration] = []
    for row in ranked:
        average = row.duration.average
        is_bottleneck = bool(average is not None and average > overall * threshold)
        flagged.append(
            StateDuration(
                state=row.state,
                count=row.count,
                duration=row.duration,
                is_bottleneck=is_bottleneck,
            )
        )
    return flagged
