"""Events package: vocabulary, payloads and dispatching.

The workflow engine observes meaningful activity and records it as immutable
:class:`~workflow_kit.events.types.DomainEvent` facts. Handlers subscribe with
:func:`subscribe` and receive a structured event for every occurrence. The
notification layer consumes these same events; it never reaches into the
engine.
"""

from workflow_kit.events.dispatcher import (
    ALL_EVENTS,
    EventDispatcher,
    Handler,
    default_dispatcher,
    dispatch,
    subscribe,
)
from workflow_kit.events.emitter import capture, emit, flush
from workflow_kit.events.types import DomainEvent, EventType, ObjectRef

__all__ = [
    "ALL_EVENTS",
    "DomainEvent",
    "EventDispatcher",
    "EventType",
    "Handler",
    "ObjectRef",
    "capture",
    "default_dispatcher",
    "dispatch",
    "emit",
    "flush",
    "subscribe",
]
