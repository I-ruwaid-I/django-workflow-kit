"""Execution and workflow-version metrics (Phase 12).

Workflow metrics answer "what is happening?" with counts derived from the
existing execution and audit tables. Counts are computed with Django
aggregations and ``Exists`` subqueries — nothing beyond the filtered set is
loaded into Python.

Outcome classification (audit events record every terminal transition as a
``workflow_completed`` row whose ``action`` is the transition name, so the
classification distinguishes reject and cancel transitions by that action):

* ``completed`` — executions with a ``workflow_completed`` audit event whose
  ``action`` is not ``reject`` or ``cancel``;
* ``rejected`` — executions with an ``approval_rejected`` audit event or a
  ``reject`` transition;
* ``cancelled`` — executions with a ``cancel`` transition (or an explicit
  ``workflow_cancelled`` audit event);
* ``failed`` — executions that reached a terminal state without any of the
  recognised completion/rejection/cancellation markers;
* ``escalated`` — executions with an ``approval_escalated`` audit event;
* ``sla_breached`` — executions whose approval slipped its ``due_at`` deadline
  (still overdue while pending, or decided after the deadline).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from workflow_kit.analytics.base import execution_queryset, parse_int

_REJECTED_EVENT = Q(event_type="approval_rejected") | Q(
    event_type="transition_executed", action="reject"
)
_REJECT_ACTION = Q(event_type="workflow_completed", action="reject")
_CANCEL_ACTION = Q(event_type="workflow_completed", action="cancel") | Q(
    event_type="workflow_cancelled"
)
_COMPLETED_ACTION = Q(event_type="workflow_completed") & ~Q(action__in=("reject", "cancel"))
_KNOWN_OUTCOME = (
    Q(event_type="workflow_completed") | Q(event_type="workflow_cancelled") | _REJECTED_EVENT
)


def _exists_event(condition: Q) -> Exists:
    """Return an ``Exists`` subquery for executions having a matching event."""
    from workflow_kit.models.history import WorkflowEvent

    events = WorkflowEvent.objects.filter(execution=OuterRef("pk"))
    return Exists(events.filter(condition))


def _exists_breached_approval() -> Exists:
    """Return an ``Exists`` subquery for executions with a breached approval."""
    from workflow_kit.models.approval import Approval, ApprovalStatus

    now = timezone.now()
    approvals = Approval.objects.filter(execution=OuterRef("pk"), due_at__isnull=False)
    breached = approvals.filter(
        Q(status=ApprovalStatus.PENDING, due_at__lt=now)
        | Q(
            status__in=[ApprovalStatus.APPROVED, ApprovalStatus.REJECTED],
            updated_at__gt=F("due_at"),
        )
    )
    return Exists(breached)


@dataclass(frozen=True)
class ExecutionMetrics:
    """Aggregated counts over a filtered set of executions."""

    started: int
    active: int
    completed: int
    rejected: int
    failed: int
    cancelled: int
    escalated: int
    sla_breached: int

    def to_dict(self) -> dict[str, int]:
        """Return a JSON-safe dictionary of the counts."""
        return {
            "started": self.started,
            "active": self.active,
            "completed": self.completed,
            "rejected": self.rejected,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "escalated": self.escalated,
            "sla_breached": self.sla_breached,
        }

    def summary(self) -> str:
        """Return a compact, human-readable one-line summary of the counts."""
        return (
            f"{self.started} started, {self.active} active, {self.completed} completed, "
            f"{self.rejected} rejected, {self.cancelled} cancelled, {self.failed} failed, "
            f"{self.escalated} escalated, {self.sla_breached} SLA breached"
        )


def execution_metrics(
    *,
    workflow: str | None = None,
    workflow_version: int | str | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    state: str | None = None,
) -> ExecutionMetrics:
    """Return aggregate counts over executions matching the filters.

    The scope is narrowed by ``workflow`` (name), ``workflow_version``
    (definition version number), ``start``/``end`` (an aware range on
    ``started_at``) and ``state`` (current execution state).
    """
    from workflow_kit.models.history import WorkflowEventType

    scope = execution_queryset(
        workflow=workflow,
        workflow_version=parse_int(workflow_version, name="workflow_version"),
        start=start,
        end=end,
        state=state,
    )
    started = scope.count()
    active = scope.filter(completed_at__isnull=True).count()
    completed = scope.filter(_exists_event(_COMPLETED_ACTION)).count()
    rejected = scope.filter(_exists_event(_REJECTED_EVENT | _REJECT_ACTION)).count()
    cancelled = scope.filter(_exists_event(_CANCEL_ACTION)).count()
    escalated = scope.filter(
        _exists_event(Q(event_type=WorkflowEventType.APPROVAL_ESCALATED))
    ).count()
    failed = scope.filter(completed_at__isnull=False).exclude(_exists_event(_KNOWN_OUTCOME)).count()
    sla_breached = scope.filter(_exists_breached_approval()).count()
    return ExecutionMetrics(
        started=started,
        active=active,
        completed=completed,
        rejected=rejected,
        failed=failed,
        cancelled=cancelled,
        escalated=escalated,
        sla_breached=sla_breached,
    )


@dataclass(frozen=True)
class VersionAnalytics:
    """Execution analytics separated by workflow definition version."""

    workflow: str
    version: int
    status: str
    started: int
    active: int
    completed: int
    rejected: int
    escalated: int
    sla_breached: int
    average_completion_seconds: float | None = None
    published_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary for this version's analytics."""
        return {
            "workflow": self.workflow,
            "version": self.version,
            "status": self.status,
            "started": self.started,
            "active": self.active,
            "completed": self.completed,
            "rejected": self.rejected,
            "escalated": self.escalated,
            "sla_breached": self.sla_breached,
            "average_completion_seconds": self.average_completion_seconds,
            "published_at": self.published_at,
        }


def version_analytics(
    *,
    workflow: str | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
) -> list[VersionAnalytics]:
    """Return per-version execution analytics so version rollouts are measurable.

    Every persisted :class:`WorkflowVersion` is reported once (optionally
    filtered to one ``workflow``). Each version's metrics come from the same
    database-side counts as :func:`execution_metrics` and the average completed
    duration reuses the completion analytics. Bound by the number of versions,
    not by execution volume.
    """
    from workflow_kit.analytics.duration import completion_metrics
    from workflow_kit.models import WorkflowVersion

    versions = WorkflowVersion.objects.all().order_by("workflow", "version")
    if workflow is not None:
        versions = versions.filter(workflow=workflow)

    rows: list[VersionAnalytics] = []
    for version in versions:
        metrics = execution_metrics(
            workflow=version.workflow,
            workflow_version=version.version,
            start=start,
            end=end,
        )
        completion = completion_metrics(
            workflow=version.workflow,
            workflow_version=version.version,
            start=start,
            end=end,
        )
        rows.append(
            VersionAnalytics(
                workflow=version.workflow,
                version=version.version,
                status=version.status,
                started=metrics.started,
                active=metrics.active,
                completed=metrics.completed,
                rejected=metrics.rejected,
                escalated=metrics.escalated,
                sla_breached=metrics.sla_breached,
                average_completion_seconds=completion.duration.average,
                published_at=version.published_at.isoformat() if version.published_at else None,
            )
        )
    return rows
