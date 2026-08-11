# Audit

Every important workflow action records an append-only
:class:`~workflow_kit.models.WorkflowEvent`. The audit trail is the single
source of truth for workflow activity; the
[timeline](timeline.md) subsystem derives its output from it.

## What gets recorded

Each event captures:

- `execution` — the workflow execution the event belongs to,
- `event_type` — a stable code (`workflow_started`, `transition_executed`,
  `approval_required`, `approval_approved`, `approval_rejected`,
  `workflow_completed`, `workflow_cancelled`),
- `action` — the transition/action name,
- `source_state` / `target_state`,
- `user` — the acting user (anonymous and system actions record no user),
- `reason` — free-form explanation (e.g. a rejection reason),
- `metadata` — optional JSON structured data (e.g. `{"approval": <id>}`),
- `created_at` — the timestamp.

## Reading the trail

```python
events = execution.history()          # ordered by created_at, then id
event = events[0]
event.event_type     # "workflow_started"
event.created_at
event.user           # User or None
```

`latest_event(execution)` returns the most recent event, if any.

## Append-only guarantee

`WorkflowEvent.save()` refuses to update an existing row: once persisted, an
event cannot be modified through the public API. Any attempt raises
`AuditError`, so historical truth is preserved.

## Recording custom events

The audit service is also the API for appending events:

```python
from workflow_kit.audit.service import record_event
from workflow_kit.models.history import WorkflowEventType

record_event(
    execution,
    event_type=WorkflowEventType.APPROVAL_APPROVED,
    action="signed",
    source_state="draft",
    target_state="approved",
    user=user,
    reason="looks fine",
    metadata={"approval": 42},
)
```