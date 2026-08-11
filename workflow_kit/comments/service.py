"""Comment service for workflow executions.

Comments attach free-form discussion text to a single execution. Adding a
comment records the author, the execution it belongs to and the moment it was
written, and appends a ``comment_added`` audit event so the discussion shows up
in the execution timeline alongside state changes and approvals.
"""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from workflow_kit.audit.service import record_event
from workflow_kit.events.service import emit_event
from workflow_kit.events.types import EventType
from workflow_kit.models.comment import WorkflowComment
from workflow_kit.models.execution import WorkflowExecution
from workflow_kit.models.history import WorkflowEventType


def add_comment(
    execution: WorkflowExecution,
    *,
    text: str,
    user: Any = None,
    metadata: dict[str, Any] | None = None,
) -> WorkflowComment:
    """Attach ``text`` as a comment on ``execution``.

    The comment is persisted with the author and the execution, then recorded
    on the audit trail (``comment_added``) and emitted as a domain event so
    handlers watching ``workflow.comment_added`` observe the discussion.
    """
    trimmed = (text or "").strip()
    comment = WorkflowComment.objects.create(
        execution=execution,
        user=_persistable_comment_user(user),
        text=trimmed,
        metadata=dict(metadata or {}),
    )
    record_event(
        execution,
        event_type=WorkflowEventType.COMMENT_ADDED,
        action="comment",
        source_state=execution.current_state,
        user=user,
        metadata={"comment_id": comment.pk, "author": comment.author_label},
    )
    emit_event(
        EventType.COMMENT_ADDED,
        execution,
        workflow=execution.workflow_name,
        source_state=execution.current_state,
        action="comment",
        user=user,
        metadata={"comment_id": comment.pk, "text": trimmed},
    )
    return comment


def execution_comments(execution: WorkflowExecution) -> QuerySet[WorkflowComment]:
    """Return every comment for ``execution``, oldest first."""
    return execution.comments.select_related("user").order_by("created_at", "id")


def _persistable_comment_user(user: Any) -> Any:
    """Return the ORM user that can be stored, or None for anonymous actors."""
    from workflow_kit.audit.service import _persistable_user

    return _persistable_user(user)
