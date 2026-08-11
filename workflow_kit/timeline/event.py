"""Structured timeline event value object.

Kept free of ORM imports so it can be exposed through the package's top-level
public API without requiring Django apps to be loaded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_LABELS = {
    "workflow_started": "Workflow started",
    "transition_executed": "State changed",
    "approval_required": "Approval required",
    "approval_approved": "Approved",
    "approval_rejected": "Rejected",
    "approval_cancelled": "Approval cancelled",
    "approval_escalated": "Escalated",
    "approval_delegated": "Delegated",
    "delegation_revoked": "Delegation revoked",
    "comment_added": "Comment added",
    "attachment_added": "Attachment added",
    "workflow_completed": "Workflow completed",
    "workflow_cancelled": "Workflow cancelled",
}


@dataclass(frozen=True)
class TimelineEvent:
    """A single, structured timeline entry.

    Applications render these themselves; the package never returns only
    pre-formatted strings.
    """

    event_type: str
    timestamp: datetime
    source_state: str = ""
    target_state: str = ""
    actor: str | None = None
    action: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """A short, human-friendly label for the event type."""
        return _LABELS.get(self.event_type, self.event_type)


def timeline_label(event_type: str) -> str:
    """Return the human-friendly label for a raw event type code."""
    return _LABELS.get(event_type, event_type)
