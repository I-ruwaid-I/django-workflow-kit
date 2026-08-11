"""Approval analytics (Phase 12).

Derived from the :class:`Approval` table, the source of truth for every
approval request and decision: requested / approved / rejected / pending /
cancelled counts plus decision-time statistics, escalation counts and
SLA-breached approvals. Grouped totals answer "where are approvals slowing
things down?" per workflow, version, step, approver or status.

Counts are calculated with database aggregations; only the two decision
timestamps of the decided approvals are pulled into Python for the duration
statistics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.db.models import Count, F, Q

from workflow_kit.analytics.base import (
    DurationStats,
    parse_datetime,
    parse_int,
)

if TYPE_CHECKING:
    from workflow_kit.models.approval import ApprovalStatus

_GROUP_FIELDS = {
    "workflow": "execution__workflow_name",
    "version": "execution__workflow_version__version",
    "step": "step",
    "approver": "approver__username",
    "status": "status",
}


@dataclass(frozen=True)
class ApprovalMetrics:
    """Aggregated approval counts and decision times over a filtered set."""

    requested: int
    approved: int
    rejected: int
    pending: int
    cancelled: int
    escalated: int
    sla_breached: int
    approved_duration: DurationStats
    rejected_duration: DurationStats

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary of the approval metrics."""
        return {
            "requested": self.requested,
            "approved": self.approved,
            "rejected": self.rejected,
            "pending": self.pending,
            "cancelled": self.cancelled,
            "escalated": self.escalated,
            "sla_breached": self.sla_breached,
            "approved_duration": self.approved_duration.to_dict(),
            "rejected_duration": self.rejected_duration.to_dict(),
        }


def _status() -> type[ApprovalStatus]:
    from workflow_kit.models.approval import ApprovalStatus

    return ApprovalStatus


def _approval_queryset(
    *,
    workflow: str | None = None,
    workflow_version: int | str | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    state: str | None = None,
) -> Any:
    """Return the :class:`Approval` rows an approval query scopes to.

    ``state`` refers to the approval's step name. The range bounds the requests
    by ``created_at``.
    """
    from workflow_kit.models import Approval as ApprovalModel

    queryset = ApprovalModel.objects.all()
    if workflow is not None:
        queryset = queryset.filter(execution__workflow_name=workflow)
    if workflow_version is not None:
        version = parse_int(workflow_version, name="workflow_version")
        if version is not None:
            queryset = queryset.filter(execution__workflow_version__version=version)
    if state is not None:
        queryset = queryset.filter(step=state)
    parsed_start = parse_datetime(start)
    parsed_end = parse_datetime(end)
    if parsed_start is not None:
        queryset = queryset.filter(created_at__gte=parsed_start)
    if parsed_end is not None:
        queryset = queryset.filter(created_at__lte=parsed_end)
    return queryset


def _breach_filter(queryset: Any) -> Any:
    """Approvals whose decision slipped the SLA deadline (late or overdue)."""
    from django.utils import timezone

    ApprovalStatus = _status()
    now = timezone.now()
    return queryset.filter(
        Q(status=ApprovalStatus.PENDING, due_at__isnull=False, due_at__lt=now)
        | Q(
            status__in=[ApprovalStatus.APPROVED, ApprovalStatus.REJECTED],
            due_at__isnull=False,
            updated_at__gt=F("due_at"),
        )
    )


def _duration_of(queryset: Any, status_label: str) -> DurationStats:
    """Decision durations (``updated_at - created_at``) for decided approvals."""
    rows = queryset.filter(status=status_label).values_list("created_at", "updated_at")
    return DurationStats.from_seconds(
        (updated - created).total_seconds() for created, updated in rows
    )


def approval_metrics(
    *,
    workflow: str | None = None,
    workflow_version: int | str | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    state: str | None = None,
) -> ApprovalMetrics:
    """Return aggregate approval analytics for the filtered approvals.

    ``state`` filters by the approval step. ``start`` / ``end`` bound the
    requested range by ``created_at``. ``approved_duration`` and
    ``rejected_duration`` summarise decision times in seconds.
    """
    from workflow_kit.models.history import WorkflowEvent as EventModel
    from workflow_kit.models.history import WorkflowEventType

    ApprovalStatus = _status()
    scope = _approval_queryset(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
        state=state,
    )
    breaches = _breach_filter(scope)
    executions = scope.values("execution_id").distinct()
    escalated = EventModel.objects.filter(
        execution_id__in=executions,
        event_type=WorkflowEventType.APPROVAL_ESCALATED,
    ).count()
    return ApprovalMetrics(
        requested=scope.count(),
        approved=scope.filter(status=ApprovalStatus.APPROVED).count(),
        rejected=scope.filter(status=ApprovalStatus.REJECTED).count(),
        pending=scope.filter(status=ApprovalStatus.PENDING).count(),
        cancelled=scope.filter(status=ApprovalStatus.CANCELLED).count(),
        escalated=escalated,
        sla_breached=breaches.count(),
        approved_duration=_duration_of(scope, ApprovalStatus.APPROVED),
        rejected_duration=_duration_of(scope, ApprovalStatus.REJECTED),
    )


def approval_totals(
    *,
    workflow: str | None = None,
    workflow_version: int | str | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    state: str | None = None,
    group_by: str = "workflow",
) -> list[dict[str, Any]]:
    """Return approved/rejected/pending/cancelled counts grouped by a dimension.

    ``group_by`` accepts ``"workflow"``, ``"version"``, ``"step"``,
    ``"approver"`` or ``"status"``. Counts are computed with a single database
    aggregation.
    """
    from workflow_kit.analytics.base import AnalyticsError

    ApprovalStatus = _status()
    key = _GROUP_FIELDS.get(group_by)
    if key is None:
        raise AnalyticsError(f"group_by must be one of {sorted(_GROUP_FIELDS)}; got {group_by!r}.")
    scope = _approval_queryset(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
        state=state,
    )
    rows = (
        scope.values(key)
        .annotate(
            approved=Count("id", filter=Q(status=ApprovalStatus.APPROVED)),
            rejected=Count("id", filter=Q(status=ApprovalStatus.REJECTED)),
            pending=Count("id", filter=Q(status=ApprovalStatus.PENDING)),
            cancelled=Count("id", filter=Q(status=ApprovalStatus.CANCELLED)),
        )
        .order_by(key)
    )
    label = group_by
    return [
        {
            "group_by": label,
            label: row[key],
            "requested": sum(
                row[field] for field in ("approved", "rejected", "pending", "cancelled")
            ),
            "approved": row["approved"],
            "rejected": row["rejected"],
            "pending": row["pending"],
            "cancelled": row["cancelled"],
        }
        for row in rows
    ]
