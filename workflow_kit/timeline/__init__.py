"""User-facing timeline derived from the workflow audit trail.

Phase 3 exposes a structured timeline through
:func:`~workflow_kit.timeline.service.execution_timeline` and the
:meth:`~workflow_kit.models.execution.WorkflowExecution.timeline` convenience.
"""

from workflow_kit.timeline.event import TimelineEvent, timeline_label

__all__ = ["TimelineEvent", "timeline_label"]
