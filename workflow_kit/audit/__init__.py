"""Append-only audit service for workflow events.

Phase 3 adds a generic audit trail. Every important workflow action is recorded
by :func:`~workflow_kit.audit.service.record_event`; records are never updated
or deleted through the public API, and the timeline derives from this trail.
"""

from workflow_kit.audit.service import event_history, record_event

__all__ = ["record_event", "event_history"]
