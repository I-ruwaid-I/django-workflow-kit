"""User-facing timeline derived from the workflow audit trail.

The timeline is a structured, deterministic view of an execution's history.
It never stores its own data: it reads the audit trail (WorkflowEvent rows)
recorded by the audit service, ordered by timestamp then primary key.
"""

from __future__ import annotations

from typing import Any

from workflow_kit.audit.service import event_history
from workflow_kit.timeline.event import TimelineEvent


def execution_timeline(execution: Any) -> list[TimelineEvent]:
    """Return the ordered, structured timeline for ``execution``."""
    return [
        TimelineEvent(
            event_type=event.event_type,
            timestamp=event.created_at,
            action=event.action,
            actor=event.user.get_username() if event.user else None,
            source_state=event.source_state,
            target_state=event.target_state,
            reason=event.reason,
            metadata=dict(event.metadata or {}),
        )
        for event in event_history(execution)
    ]
