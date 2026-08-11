"""Build domain events from engine state.

These helpers translate a persisted workflow change into an immutable
:class:`~workflow_kit.events.types.DomainEvent`. They are called by the engine
alongside the audit trail so that every recorded fact also has an observable
event without duplicating the audit logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils import timezone

from workflow_kit.events.emitter import emit
from workflow_kit.events.types import DomainEvent, EventType, ObjectRef

if TYPE_CHECKING:
    from workflow_kit.models.execution import WorkflowExecution


def _object_ref(execution: WorkflowExecution) -> ObjectRef:
    content_type = execution.content_type
    return ObjectRef(
        app_label=content_type.app_label,
        model_name=content_type.model,
        pk=execution.object_id,
        display=str(execution.object) if execution.object_id else "",
    )


def _actor(user: Any) -> str | None:
    """Return a stable actor label, or None for anonymous/absent actors."""
    if user is None:
        return None
    name = getattr(user, "get_username", None)
    if callable(name):
        return name() or None
    username = getattr(user, "username", None)
    return str(username) if username else str(user)


def emit_event(
    event_type: EventType,
    execution: WorkflowExecution,
    *,
    workflow: str,
    source_state: str = "",
    target_state: str = "",
    action: str = "",
    user: Any = None,
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> DomainEvent:
    """Emit a domain event describing ``execution``'s latest change."""
    payload = metadata or {}
    if reason:
        payload = {**payload, "reason": reason}
    version = getattr(execution, "workflow_version_number", None)
    event = DomainEvent(
        type=event_type,
        workflow=workflow,
        execution_id=execution.pk,
        object=_object_ref(execution),
        actor=_actor(user),
        timestamp=timezone.now(),
        source_state=source_state,
        target_state=target_state,
        action=action,
        metadata=payload,
        workflow_version=version,
    )
    emit(event)
    return event
