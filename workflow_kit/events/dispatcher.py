"""Explicit, in-process event dispatching.

The dispatcher is the single place handlers can subscribe to domain events. It
is deliberately *not* Django signals: registration is explicit, handlers are
typed, cleanup is trivial from unit tests and nothing about Django's app
lifecycle is required.

Handlers are invoked synchronously. A failing handler must never corrupt
workflow state, so each handler is guarded: exceptions are logged and
swallowed for the rest of the dispatch loop.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from workflow_kit.events.types import EventType

if TYPE_CHECKING:
    from workflow_kit.events.types import DomainEvent

logger = logging.getLogger(__name__)

Handler = Callable[["DomainEvent"], None]

# Subscribing to ``"*"`` matches every event type.
ALL_EVENTS = "*"


class EventDispatcher:
    """A registry mapping event types to ordered handler callables."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self._all_handlers: list[Handler] = []

    def subscribe(  # noqa: A003
        self,
        event_type: EventType | str,
        handler: Handler,
    ) -> Callable[[], None]:
        """Register ``handler`` for ``event_type`` and return an unsubscribe callable.

        ``event_type`` may be an :class:`EventType`, one of its string values
        (``"workflow.completed"``) or ``"*"`` to receive every event.
        """
        if not callable(handler):
            raise TypeError("Event handlers must be callable.")
        key = str(event_type)
        if key == ALL_EVENTS:
            self._all_handlers.append(handler)
        else:
            self._handlers.setdefault(key, []).append(handler)

        def unsubscribe() -> None:
            bucket = self._all_handlers if key == ALL_EVENTS else self._handlers.get(key)
            if bucket is not None and handler in bucket:
                bucket.remove(handler)

        return unsubscribe

    def dispatch(self, event: DomainEvent) -> None:
        """Invoke every handler subscribed for ``event.type``, then wildcards.

        Handler exceptions are logged and isolated; they never propagate and
        therefore never affect workflow or transaction state.
        """
        for handler in list(self._handlers.get(str(event.type), [])) + list(self._all_handlers):
            try:
                handler(event)
            except Exception:  # noqa: BLE001 - intentionally fault-isolated
                logger.exception("Event handler for '%s' failed.", event.type)

    def clear(self) -> None:
        """Remove all registered handlers (mainly useful in tests)."""
        self._handlers.clear()
        self._all_handlers.clear()


default_dispatcher = EventDispatcher()


# -- convenient public aliases ------------------------------------------------


def subscribe(event_type: EventType | str, handler: Handler) -> Callable[[], None]:
    """Subscribe ``handler`` to ``event_type`` on the default dispatcher."""
    return default_dispatcher.subscribe(event_type, handler)


def dispatch(event: DomainEvent) -> None:
    """Dispatch ``event`` to the default dispatcher's handlers."""
    default_dispatcher.dispatch(event)
