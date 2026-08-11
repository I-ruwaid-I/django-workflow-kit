"""Transaction-aware event emission.

The engine records :class:`DomainEvent` objects with :func:`emit` at the exact
moment a state-change fact becomes real. Delivery is transaction aware:

* The engine wraps each operation in :func:`capture`. Events recorded inside
  are buffered and dispatched together when the operation succeeds. If the
  operation fails (e.g. the transition raises), the captured events are
  discarded, so a rolled-back transition never delivers events.
* Events emitted outside a :func:`capture` block are dispatched immediately,
  so unit tests and ad-hoc handlers observe them synchronously.

This separates "event generated" (a :class:`DomainEvent` was produced) from
"event delivered" (handlers were invoked), and keeps handler side effects out
of the workflow transaction. External delivery layers (email, webhooks) can add
an extra ``transaction.on_commit`` guard in their providers.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from workflow_kit.events.dispatcher import default_dispatcher

if TYPE_CHECKING:
    from workflow_kit.events.types import DomainEvent

_lock = threading.Lock()
_collector: list[DomainEvent] | None = None


@contextmanager
def capture() -> Iterator[list[DomainEvent]]:
    """Capture events emitted inside the block, dispatching them on success.

    On normal exit the captured events are dispatched, in order, through the
    default dispatcher. On an exception the events are discarded so a failed
    workflow operation never delivers events.
    """
    global _collector
    captured: list[DomainEvent] = []
    with _lock:
        parent = _collector
        _collector = captured
    success = False
    try:
        yield captured
        success = True
    finally:
        with _lock:
            _collector = parent
    if success and parent is None:
        for event in captured:
            default_dispatcher.dispatch(event)


def emit(event: DomainEvent) -> None:
    """Record ``event`` to the active capture, or dispatch it directly."""
    with _lock:
        collector = _collector
        if collector is not None:
            collector.append(event)
            return
    default_dispatcher.dispatch(event)


def flush(events: list[DomainEvent]) -> int:
    """Dispatch a pre-collected list of events in order (idempotent helper)."""
    for event in events:
        default_dispatcher.dispatch(event)
    return len(events)
