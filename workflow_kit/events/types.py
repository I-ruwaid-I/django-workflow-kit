"""Domain event vocabulary and payload for Django Workflow Kit.

A :class:`DomainEvent` is an immutable, structured description of something
that happened to a workflow execution. The workflow engine generates these
facts but never lets them drive its own state; notifications, webhooks and
application handlers observe the same stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class EventType(StrEnum):
    """Stable internal event identifiers.

    Names follow the ``workflow.<thing>`` convention so that handlers can
    subscribe generically while the audit trail keeps the package's
    snake_case event codes.
    """

    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_TRANSITIONED = "workflow.transitioned"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_CANCELLED = "workflow.cancelled"
    WORKFLOW_REJECTED = "workflow.rejected"
    APPROVAL_CREATED = "approval.created"
    APPROVAL_APPROVED = "approval.approved"
    APPROVAL_REJECTED = "approval.rejected"
    APPROVAL_CANCELLED = "approval.cancelled"
    APPROVAL_ESCALATED = "approval.escalated"
    APPROVAL_DELEGATED = "approval.delegated"
    COMMENT_ADDED = "workflow.comment_added"
    ATTACHMENT_ADDED = "workflow.attachment_added"


@dataclass(frozen=True)
class ObjectRef:
    """A controlled reference to the business object of an execution.

    Holds only the stable identity (app label, model name and primary key)
    plus a readable string, never arbitrary internal state.
    """

    app_label: str
    model_name: str
    pk: Any
    display: str = ""

    def scope(self) -> str:
        """Return the ``app_label.Model`` reference string."""
        return f"{self.app_label}.{self.model_name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.scope(),
            "id": self.pk,
            "display": self.display,
        }


@dataclass(frozen=True)
class DomainEvent:
    """A structured, immutable description of a single workflow event.

    All fields are resolved and frozen at construction time. Handlers receive
    this object as-is and should never attempt to mutate it.

    ``id`` is a unique marker for the occurrence so consumers (and in
    particular webhook clients) can deduplicate deliveries.
    """

    type: EventType
    workflow: str
    execution_id: int
    object: ObjectRef
    actor: str | None
    timestamp: datetime
    source_state: str = ""
    target_state: str = ""
    action: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    workflow_version: int | None = None
    id: str = field(default_factory=lambda: uuid4().hex)
