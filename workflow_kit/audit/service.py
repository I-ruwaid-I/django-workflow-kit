"""Append-only audit service for workflow events.

Every important workflow action records a :class:`WorkflowEvent` here. The
timeline subsystem derives its output from history recorded by this service so
there is a single source of truth for workflow activity.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Model, QuerySet

from workflow_kit.models.history import WorkflowEvent, WorkflowEventType


def _persistable_user(user: Any) -> Any:
    """Return ``user`` when it can be stored on a foreign key, else None.

    Anonymous users (which are not ORM model instances) and model-less actors
    are recorded as no actor rather than raising a foreign-key error.
    """
    if isinstance(user, Model) and getattr(user, "pk", None) is not None:
        return user
    return None


def record_event(
    execution: Any,
    *,
    event_type: WorkflowEventType | str,
    action: str = "",
    source_state: str = "",
    target_state: str = "",
    user: Any = None,
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> WorkflowEvent:
    """Append a ``WorkflowEvent`` to ``execution``'s audit trail.

    When ``execution`` is bound to a workflow version, the version number is
    stamped into the event metadata so historical records stay understandable
    even after newer versions exist.
    """
    payload = dict(metadata or {})
    version = getattr(execution, "workflow_version_number", None)
    if version is not None:
        payload.setdefault("workflow_version", version)
    return WorkflowEvent.objects.create(
        execution=execution,
        event_type=str(event_type),
        action=action,
        source_state=source_state,
        target_state=target_state,
        user=_persistable_user(user),
        reason=reason,
        metadata=payload,
    )


def event_history(execution: Any) -> QuerySet[WorkflowEvent]:
    """Return the ordered, immutable audit trail for ``execution``.

    Events are ordered by timestamp and, as a deterministic tie-breaker for
    identical timestamps, by ascending primary key.
    """
    return (
        WorkflowEvent.objects.filter(execution=execution)
        .select_related("user")
        .order_by("created_at", "id")
    )


def latest_event(execution: Any) -> WorkflowEvent | None:
    """Return the most recent audit event for ``execution``, if any."""
    return event_history(execution).last()
