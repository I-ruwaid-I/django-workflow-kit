# Observability

Phase 12 adds a small observability layer with two orthogonal concerns:

1. **Correlation ids** — a context-scoped identifier that lets logs, event
   handlers, notifications and webhooks from the *same* request be tied
   together.
2. **Structured event logging** — a logger that records every domain event the
   engine emits as a JSON-friendly structured log record.

This reuses the Phase 5 domain event stream: it is *not* a second event
system, and it never changes workflow behaviour or writes to the database.

## Correlation ids

```python
from workflow_kit.observability import correlation_id, current_correlation_id

with correlation_id():            # generates a UUID
    execution.transition("approve", user=user)

with correlation_id("req-8f3a"):  # or provide your own
    ...                           # nested scopes restore the outer id

current_correlation_id()          # None outside any scope
```

Behind the scenes these are `contextvars`, so the value is isolated per
asyncio task / thread and automatically restored when a scope exits. The
low-level `set_correlation_id` / `reset_correlation_id` functions exist for
code that cannot use the context manager (for example a custom middleware).

## Structured event logging

A `StructuredEventLogger` subscribes to the default event dispatcher and logs
each `DomainEvent` at `INFO` with a `workflow_event` extra carrying a
JSON-friendly payload:

```json
{
  "event": "workflow.started",
  "workflow": "invoice_approval",
  "version": 2,
  "execution_id": 41,
  "object_type": "demo.Invoice",
  "object_id": 7,
  "source_state": "draft",
  "target_state": "manager_review",
  "action": "submit",
  "actor": "alice",
  "correlation_id": "req-8f3a"
}
```

Plug the payload into your logging pipeline by attaching an ext processor /
formatter that reads `record.workflow_event`.

### Automatic installation

The app config installs the logger automatically when the app `ready()` runs
(that is, whenever `workflow_kit` is in `INSTALLED_APPS`). To opt out:

```python
WORKFLOW_KIT = {
    "STRUCTURED_LOGGING": False,
}
```

### Manual control

```python
from workflow_kit.observability import (
    install_structured_logging,
    uninstall_structured_logging,
)

install_structured_logging()            # idempotent; subscribes to all events
uninstall_structured_logging()          # removes it again; returns True/False
```

You can install against a specific logger and correlation provider:

```python
import logging
from workflow_kit.observability import install_structured_logging

install_structured_logging(
    log=logging.getLogger("my_app.workflow"),
    correlation_provider=current_correlation_id,
)
```

## Correlation in practice

The structured payload embeds whatever `current_correlation_id()` returns at
log time. To correlate the REST request, its notifications and its audit trail:

1. Set the correlation id at the request boundary (`correlation_id()`, or a
   small middleware calling `set_correlation_id(...)`).
2. Let the workflow run — every domain event that request triggers is logged
   under the same id.
3. Search your log aggregator for the id and follow the whole flow, including
   the URLs webhooks delivered.

See also [Events](events.md) for the underlying `DomainEvent` vocabulary, and
[Analytics](analytics.md) for the aggregate query layer that complements
manual log inspection.