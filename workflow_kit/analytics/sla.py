"""SLA and escalation analytics (Phase 12).

SLA analytics answer "how often are SLAs breached?" using the approvals'
``due_at`` deadlines: an approval is on time when it is decided before its
deadline, breached when it is still overdue while pending or decided after the
deadline. Escalation analytics answer "how are escalations distributed?" from
the ``approval_escalated`` audit events, whose ``reason`` and ``source_state``
carry the escalation context.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.db.models import F, Q
from django.utils import timezone

from workflow_kit.analytics.approvals import _approval_queryset
from workflow_kit.analytics.duration import completion_metrics

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class SlaMetrics:
    """SLA compliance over a filtered set of approvals.

    ``tracked`` counts approvals with a ``due_at`` deadline; ``decided`` the
    tracked ones that were decided; ``on_time`` the decided-before-deadline
    ones; ``breached`` those that slipped (late decision or overdue-while-
    pending). ``compliance_rate`` is ``on_time / decided * 100`` (``None`` when
    nothing has been decided). ``average_overdue`` is the mean seconds by which
    breached approvals passed their deadline.
    """

    tracked: int
    decided: int
    on_time: int
    breached: int
    pending_overdue: int
    compliance_rate: float | None
    average_overdue: float | None
    escalation_count: int
    average_completion_time: float | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary of the SLA metrics."""
        return {
            "tracked": self.tracked,
            "decided": self.decided,
            "on_time": self.on_time,
            "breached": self.breached,
            "pending_overdue": self.pending_overdue,
            "compliance_rate": self.compliance_rate,
            "average_overdue": self.average_overdue,
            "escalation_count": self.escalation_count,
            "average_completion_time": self.average_completion_time,
        }


def _breach_filter(now: datetime) -> Q:
    """Approvals that slipped their SLA deadline at ``now``."""
    from workflow_kit.models.approval import ApprovalStatus

    return Q(
        status=ApprovalStatus.PENDING,
        due_at__isnull=False,
        due_at__lt=now,
    ) | Q(
        status__in=[ApprovalStatus.APPROVED, ApprovalStatus.REJECTED],
        due_at__isnull=False,
        updated_at__gt=F("due_at"),
    )


def sla_metrics(
    *,
    workflow: str | None = None,
    workflow_version: int | str | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    state: str | None = None,
) -> SlaMetrics:
    """Return SLA compliance analytics for the filtered approvals.

    ``state`` filters by the approval step; the range bounds approvals by
    ``created_at``. ``average_completion_time`` reuses the execution completion
    analytics for the same workflow scope (in seconds).
    """
    from workflow_kit.models.approval import ApprovalStatus

    scope = _approval_queryset(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
        state=state,
    )
    now = timezone.now()
    tracked = scope.filter(due_at__isnull=False)
    decided = tracked.filter(status__in=[ApprovalStatus.APPROVED, ApprovalStatus.REJECTED])

    decided_count = decided.count()
    breach_decided = decided.filter(updated_at__gt=F("due_at")).count()
    pending_overdue = tracked.filter(
        status=ApprovalStatus.PENDING,
        due_at__lt=now,
    ).count()
    on_time = decided_count - breach_decided
    breached_count = breach_decided + pending_overdue
    compliance_rate = (on_time / decided_count * 100) if decided_count else None

    overdue = [
        (updated - due_at).total_seconds()
        for due_at, updated in decided.filter(updated_at__gt=F("due_at")).values_list(
            "due_at", "updated_at"
        )
    ]
    current_overdue = [
        (now - due_at).total_seconds() for due_at in _pending_overdue_times(tracked, now)
    ]
    average_overdue = _average(tuple(overdue + current_overdue))

    escalation_count = _escalation_scope(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
        scope=tracked,
    )

    completion = completion_metrics(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
    )
    return SlaMetrics(
        tracked=tracked.count(),
        decided=decided_count,
        on_time=on_time,
        breached=breached_count,
        pending_overdue=pending_overdue,
        compliance_rate=compliance_rate,
        average_overdue=average_overdue,
        escalation_count=escalation_count,
        average_completion_time=completion.duration.average,
    )


def _pending_overdue_times(tracked: Any, now: datetime) -> list[datetime]:
    """Overdue seconds for approvals still pending past their deadline."""
    from workflow_kit.models.approval import ApprovalStatus

    pending = tracked.filter(status=ApprovalStatus.PENDING, due_at__lt=now)
    return [due_at for (due_at,) in pending.values_list("due_at")]


def _escalation_scope(
    *,
    workflow: str | None,
    workflow_version: int | str | None,
    start: datetime | str | None,
    end: datetime | str | None,
    scope: Any,
) -> int:
    """Count ``approval_escalated`` audit events for the approval scope."""
    from workflow_kit.analytics.base import parse_datetime
    from workflow_kit.models.history import WorkflowEvent, WorkflowEventType

    events = WorkflowEvent.objects.filter(
        execution_id__in=scope.values("execution_id").distinct(),
        event_type=WorkflowEventType.APPROVAL_ESCALATED,
    )
    parsed_start = parse_datetime(start)
    parsed_end = parse_datetime(end)
    if parsed_start is not None:
        events = events.filter(created_at__gte=parsed_start)
    if parsed_end is not None:
        events = events.filter(created_at__lte=parsed_end)
    return events.count()


def _average(values: tuple[float, ...]) -> float | None:
    return sum(values) / len(values) if values else None


def escalation_analytics(
    *,
    workflow: str | None = None,
    workflow_version: int | str | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
) -> dict[str, Any]:
    """Return escalation distribution over a filtered set of executions.

    Reports the total escalation count plus breakdowns by workflow, state
    (``source_state``), reason and the average seconds between an approval's
    creation and its escalation event. Escalations are recorded as
    ``approval_escalated`` audit events carrying the act, so no separate
    escalation table is consulted.
    """
    from workflow_kit.analytics.base import parse_datetime
    from workflow_kit.analytics.base import parse_int as _version
    from workflow_kit.models.history import WorkflowEvent, WorkflowEventType

    executions = _execution_scope(
        workflow=workflow,
        workflow_version=_version(workflow_version, name="workflow_version"),
        start=start,
        end=end,
    )
    events = WorkflowEvent.objects.filter(
        execution__in=executions,
        event_type=WorkflowEventType.APPROVAL_ESCALATED,
    )
    parsed_start = parse_datetime(start)
    parsed_end = parse_datetime(end)
    if parsed_start is not None:
        events = events.filter(created_at__gte=parsed_start)
    if parsed_end is not None:
        events = events.filter(created_at__lte=parsed_end)
    rows = events.order_by("created_at", "id").values(
        "id",
        "execution_id",
        "execution__workflow_name",
        "source_state",
        "reason",
        "created_at",
        "metadata",
    )

    by_workflow: dict[str, int] = {}
    by_state: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    approval_ids: set[str] = set()
    event_times: dict[str, datetime] = {}
    for row in rows:
        by_workflow[row["execution__workflow_name"]] = (
            by_workflow.get(row["execution__workflow_name"], 0) + 1
        )
        by_state[row["source_state"]] = by_state.get(row["source_state"], 0) + 1
        reason = row["reason"].strip() or "(no reason)"
        by_reason[reason] = by_reason.get(reason, 0) + 1
        approval_id = row["metadata"].get("approval") if isinstance(row["metadata"], dict) else None
        if approval_id is not None:
            mark = str(approval_id)
            approval_ids.add(mark)
            event_times[mark] = row["created_at"]

    average_delay = _escalation_delay(approval_ids, event_times)
    return {
        "total": sum(by_workflow.values()),
        "by_workflow": _ranked(by_workflow),
        "by_state": _ranked(by_state),
        "by_reason": _ranked(by_reason),
        "average_delay_seconds": average_delay,
    }


def _execution_scope(
    *,
    workflow: str | None,
    workflow_version: int | None,
    start: datetime | str | None,
    end: datetime | str | None,
) -> Any:
    """Return the executions an escalation query scopes to (by workflow/version/range)."""
    from workflow_kit.analytics.base import execution_queryset

    return execution_queryset(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
    )


def _escalation_delay(approval_ids: set[str], event_times: dict[str, datetime]) -> float | None:
    """Average seconds between an approval's creation and its escalation."""
    if not approval_ids:
        return None
    from workflow_kit.models.approval import Approval

    approvals = Approval.objects.filter(pk__in=[int(pk) for pk in approval_ids]).values_list(
        "pk", "created_at"
    )
    created = {str(pk): created_at for pk, created_at in approvals}
    delays = [
        (event_times[mark] - created[mark]).total_seconds()
        for mark in approval_ids
        if mark in created
    ]
    return _average(tuple(delays))


def _ranked(counter: dict[str, int]) -> list[dict[str, Any]]:
    """Render a ``{key: count}`` map as a sorted decomposition list."""
    return [
        {"key": key, "count": count}
        for key, count in sorted(counter.items(), key=lambda item: item[1], reverse=True)
    ]
