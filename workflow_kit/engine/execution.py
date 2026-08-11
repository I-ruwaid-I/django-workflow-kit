"""Workflow execution logic backed by the Django ORM.

These helpers implement the transition lifecycle: start executions, resolve
them for a business object and apply transitions atomically with database-level
locking where the backend supports it. Every transition records audit events
and approval requirements through :func:`workflow_kit.engine.effects.apply_transition`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction

from workflow_kit.conf import settings as workflow_settings
from workflow_kit.engine.effects import apply_transition
from workflow_kit.exceptions import (
    PermissionDeniedError,
    WorkflowAlreadyCompletedError,
    WorkflowNotFoundError,
)
from workflow_kit.permissions.evaluate import is_authorized

if TYPE_CHECKING:
    from django.db.models import Model

    from workflow_kit.engine.workflow import Workflow
    from workflow_kit.models.execution import WorkflowExecution


def start_execution(
    workflow: Workflow,
    obj: Model,
    *,
    user: Any = None,
    version: Any = None,
    allow_unpublished: bool = False,
) -> WorkflowExecution:
    """Create a new execution of ``workflow`` for ``obj`` in its initial state.

    ``user`` is optionally recorded as the execution's initiator so self-approval
    rules (Phase 9) can be enforced for steps that disallow self-approval.

    ``version`` optionally pins the execution to a specific version (an int or a
    :class:`WorkflowVersion`). Without it, the workflow's active published
    version is selected; when no versions exist the execution stays unversioned
    (legacy definition-in-Python behaviour).
    """
    from workflow_kit.audit.service import _persistable_user, record_event
    from workflow_kit.engine.versioning import resolve_start_version
    from workflow_kit.events import capture
    from workflow_kit.events.service import emit_event
    from workflow_kit.events.types import EventType
    from workflow_kit.models import WorkflowExecution
    from workflow_kit.models.history import WorkflowEventType

    version_row = resolve_start_version(
        workflow,
        version,
        allow_unpublished=allow_unpublished,
    )
    with capture():
        execution = WorkflowExecution.objects.create(
            workflow_name=workflow.name,
            workflow_version=version_row,
            object=obj,
            current_state=workflow.initial,
            initiated_by=_persistable_user(user),
        )
        record_event(
            execution,
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            action="start",
            target_state=workflow.initial,
            user=user,
        )
        emit_event(
            EventType.WORKFLOW_STARTED,
            execution,
            workflow=workflow.name,
            target_state=workflow.initial,
            action="start",
            user=user,
        )
    return execution


def get_execution(workflow: Workflow, obj: Model) -> WorkflowExecution:
    """Return the execution of ``workflow`` for ``obj``.

    Raises :class:`WorkflowNotFoundError` when no execution exists.
    """
    from django.contrib.contenttypes.models import ContentType

    from workflow_kit.models import WorkflowExecution

    content_type = ContentType.objects.get_for_model(obj)
    try:
        return WorkflowExecution.objects.get(
            workflow_name=workflow.name,
            content_type=content_type,
            object_id=obj.pk,
        )
    except WorkflowExecution.DoesNotExist as exc:
        raise WorkflowNotFoundError(
            f"No execution of workflow '{workflow.name}' exists for {obj!r}."
        ) from exc


def execute_transition(
    workflow: Workflow,
    execution: WorkflowExecution,
    action: str,
    user: Any = None,
) -> WorkflowExecution:
    """Apply ``action`` to ``execution`` atomically and return the execution.

    The execution row is locked with ``select_for_update`` (where the database
    backend supports it) and the current state is re-validated under the lock
    before the change is persisted.
    """
    from workflow_kit.engine.versioning import get_workflow_for_execution
    from workflow_kit.models import WorkflowExecution

    def _apply() -> WorkflowExecution:
        locked = WorkflowExecution.objects.select_for_update().get(pk=execution.pk)
        current = locked.current_state

        # Version-bound executions must resolve every transition against the
        # definition they started with, never the live registered one (Phase 9).
        # Legacy (unversioned) executions keep using the caller's definition.
        bounded_workflow = get_workflow_for_execution(locked)
        if locked.workflow_version_id is None:
            bounded_workflow = workflow

        if bounded_workflow.is_terminal(current):
            raise WorkflowAlreadyCompletedError(
                f"Workflow '{bounded_workflow.name}' is already completed in state '{current}'."
            )

        # Condition-aware resolution re-reads the business object inside the
        # transaction, so conditions are always evaluated against fresh state.
        transition = bounded_workflow.resolve_transition(locked, action, user=user)

        if not is_authorized(user, bounded_workflow, locked, transition):
            raise PermissionDeniedError(f"User is not authorized to execute transition '{action}'.")

        result = apply_transition(locked, bounded_workflow, transition, user=user)
        # Mirror the fresh state back onto the caller's object so its identity
        # and state stay in sync after the transition.
        execution.current_state = result.current_state
        execution.completed_at = result.completed_at
        execution.updated_at = result.updated_at
        return execution

    result: WorkflowExecution | None = None
    if workflow_settings.ATOMIC_TRANSITIONS:
        from workflow_kit.events import capture

        with capture(), transaction.atomic():
            result = _apply()
    else:
        result = _apply()

    return result
