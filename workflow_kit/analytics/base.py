"""Shared building blocks for the Phase 12 analytics layer.

Everything here is read-only: analytics derive aggregated information from the
existing tables (executions, approvals, audit events, versions) and never
write to the database. The public API functions live in the sibling modules;
this module provides the shared filtering helpers, date parsing and duration
statistics.

Date ranges are timezone-aware. Plain datetimes passed to the analytics
functions are interpreted in the current Django time zone (``settings.USE_TZ``
semantics preserved); ISO ``str`` values are parsed and made aware the same
way.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median as _median
from typing import TYPE_CHECKING, Any

from django.db.models import QuerySet
from django.utils import dateparse, timezone

if TYPE_CHECKING:
    from workflow_kit.models.execution import WorkflowExecution


class AnalyticsError(ValueError):
    """Raised when analytics arguments are invalid (e.g. a bad date range)."""


def parse_datetime(value: datetime | str | None) -> datetime | None:
    """Coerce ``value`` to an aware :class:`datetime`, or ``None``.

    Naive datetimes and ISO strings without an offset are interpreted in the
    current Django time zone. Strings that cannot be parsed raise
    :class:`AnalyticsError`.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed: datetime = value
    else:
        parsed_string = dateparse.parse_datetime(value)
        if parsed_string is None:
            raise AnalyticsError(f"Cannot parse datetime from {value!r}.")
        parsed = parsed_string
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed)
    return parsed


def execution_queryset(
    *,
    workflow: str | None = None,
    workflow_version: int | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    state: str | None = None,
) -> QuerySet[WorkflowExecution]:
    """Return the :class:`WorkflowExecution` rows an analytics query scopes to.

    ``start`` / ``end`` bound the range by ``started_at``. ``workflow_version``
    restricts to executions pinned to that definition version number.
    """
    from workflow_kit.models import WorkflowExecution

    queryset = WorkflowExecution.objects.all()
    if workflow is not None:
        queryset = queryset.filter(workflow_name=workflow)
    if workflow_version is not None:
        queryset = queryset.filter(workflow_version__version=workflow_version)
    parsed_start = parse_datetime(start)
    parsed_end = parse_datetime(end)
    if parsed_start is not None:
        queryset = queryset.filter(started_at__gte=parsed_start)
    if parsed_end is not None:
        queryset = queryset.filter(started_at__lte=parsed_end)
    if state is not None:
        queryset = queryset.filter(current_state=state)
    return queryset


def parse_int(value: str | int | None, *, name: str) -> int | None:
    """Coerce a query value to ``int``, validating it is a whole number."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AnalyticsError(f"{name} must be an integer, got {value!r}.") from exc


def _seconds(delta: timedelta | None) -> float | None:
    """Convert a timedelta to seconds, ``None`` when absent."""
    return delta.total_seconds() if delta is not None else None


@dataclass(frozen=True)
class DurationStats:
    """Summary statistics over a set of durations (in seconds).

    ``average``, ``median``, ``minimum``, ``maximum``, ``p95`` and ``p99`` are
    ``None`` when ``count`` is zero.
    """

    count: int
    average: float | None = None
    median: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    p95: float | None = None
    p99: float | None = None

    @classmethod
    def from_seconds(cls, values: Iterable[float]) -> DurationStats:
        """Build stats from an iterable of durations in seconds.

        ``values`` is consumed exactly once. A single pass computes the count,
        average and min/max; the median and percentiles sort the values. An
        empty iterable produces zeroed stats with ``None`` aggregates.
        """
        data = [float(v) for v in values]
        count = len(data)
        if count == 0:
            return DurationStats(count=0)
        average = sum(data) / count
        minimum = min(data)
        maximum = max(data)
        ordered = sorted(data)
        return DurationStats(
            count=count,
            average=average,
            median=_median(ordered),
            minimum=minimum,
            maximum=maximum,
            p95=_quantile(ordered, 0.95),
            p99=_quantile(ordered, 0.99),
        )

    @classmethod
    def from_deltas(cls, values: Iterable[timedelta | None]) -> DurationStats:
        """Build stats from an iterable of timedeltas (``None`` values skipped)."""
        seconds: list[float] = []
        for value in values:
            if value is not None:
                seconds.append(value.total_seconds())
        return cls.from_seconds(seconds)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary of the statistics."""
        return {
            "count": self.count,
            "average": self.average,
            "median": self.median,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "p95": self.p95,
            "p99": self.p99,
        }

    def __bool__(self) -> bool:
        return self.count > 0


def _quantile(ordered: list[float], q: float) -> float:
    """Nearest-rank quantile over an already sorted list of floats."""
    if not ordered:
        raise ValueError("Cannot compute a quantile of an empty sequence.")
    index = min(len(ordered) - 1, max(0, round(q * len(ordered)) - 1))
    return ordered[index]


def _iso_format(value: datetime | None) -> str | None:
    """Render an aware datetime as ISO with timezone info, else ``None``."""
    if value is None:
        return None
    return value.isoformat()
