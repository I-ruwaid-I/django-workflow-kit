# Events

The engine records every meaningful workflow fact as a **domain event**: an
immutable, structured description of something that happened to a workflow
execution. Events are emitted by the engine at the moment a state-change fact
becomes real, and applications subscribe to react — without touching the engine
itself.

```text
Workflow Started ──► Event ──► Handler
Transition           │          Notification
Approval             │          Webhook
Workflow Completed   │          Audit
                     │          Custom consumer
                     └────────► (anything)
```

## Event types

```python
from workflow_kit import EventType

EventType.WORKFLOW_STARTED       # "workflow.started"
EventType.WORKFLOW_TRANSITIONED  # "workflow.transitioned"
EventType.WORKFLOW_COMPLETED     # "workflow.completed"
EventType.WORKFLOW_CANCELLED     # "workflow.cancelled"
EventType.WORKFLOW_REJECTED      # "workflow.rejected"
EventType.APPROVAL_CREATED       # "approval.created"
EventType.APPROVAL_APPROVED      # "approval.approved"
EventType.APPROVAL_REJECTED      # "approval.rejected"
```

## The event payload

A [`DomainEvent`](api.md) carries structured facts: `type`, `workflow`,
`execution_id`, `object` (an `ObjectRef` with `app_label`, `model_name`, `pk`
and `display`), `actor`, `timestamp`, `source_state`, `target_state`, `action`
and an arbitrary `metadata` dictionary.

Events are immutable — once emitted, their core identity never changes. Each
event also has a unique `id` so consumers (for example webhook receivers) can
deduplicate deliveries.

## Subscribing

Subscribe a handler on the default dispatcher:

```python
from workflow_kit import EventType
from workflow_kit.events import subscribe

def on_completed(event):
    print(event.object.display, "completed")

unsubscribe = subscribe(EventType.WORKFLOW_COMPLETED, on_completed)
```

The returned callable removes the handler when no longer needed. Handlers may
subscribe to a specific event name (a string), an `EventType`, or `"*"` to
receive every event.

```python
from workflow_kit.events import ALL_EVENTS

subscribe(ALL_EVENTS, log_everything)
```

Handler failures are isolated: if one handler raises, the exception is logged
and the other handlers still run. A failing handler can never corrupt workflow
state.

## Transaction-aware emission

The engine wraps each operation (starting an execution, applying a transition,
deciding an approval) in a `capture` block. Events recorded inside it are
buffered and dispatched together only when the operation succeeds:

```text
Transition
  ├── state changes
  ├── audit event recorded
  ├── events captured
  └── commit success ──► events dispatched in order
```

If the operation fails and the transaction rolls back, the captured events are
**discarded** — a rolled-back transition never delivers events.

Events emitted outside any capture block are dispatched immediately, so unit
tests and ad-hoc handlers observe them synchronously.

```python
from workflow_kit.events import capture

with capture():
    emit(some_event())   # buffered
# dispatched here if the block succeeded
```

## Delivery semantics

The Phase 5 event system provides:

- **Synchronous** dispatch (handlers run in the same process/thread).
- **In-process** — no message broker yet.
- **Best-effort** — if a process crashes between emissions and dispatch, events
  may be lost. External delivery (email, webhooks) should add retry/idempotency
  at an application level; this is deliberately not claimed to be guaranteed.

## What the engine emits

| Operation                        | Events                            |
| -------------------------------- | --------------------------------- |
| `workflow.start(...)`            | `workflow.started`                |
| Transition to a non-terminal     | `workflow.transitioned`, `approval.created` |
| Transition to a terminal state   | `workflow.transitioned`, `workflow.completed` |
| Reject transition                 | `workflow.transitioned`, `workflow.rejected` |
| Approve via the approval layer   | `approval.approved`               |
| Reject via the approval layer    | `approval.rejected`, `workflow.rejected` |

The notification layer (`NotificationRouter`) consumes these same events — it
never reaches into the engine, and it is not the only possible consumer.

## See also

- [Notifications](notifications.md)
- Notifications are built on top of the same event stream (see how they
  subscribe in the router)