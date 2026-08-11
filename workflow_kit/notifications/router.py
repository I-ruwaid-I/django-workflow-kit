"""A notification router that turns domain events into provider deliveries.

The router subscribes to the domain event dispatcher. For each registered
``event_type`` it hands the matching events to a :class:`NotificationProvider`,
which builds and delivers a :class:`Notification`. Notification orchestration
lives here, never in the workflow engine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from workflow_kit.events import EventDispatcher, default_dispatcher
from workflow_kit.notifications.base import NotificationProvider

if TYPE_CHECKING:
    from workflow_kit.events.types import DomainEvent

logger = logging.getLogger(__name__)


class NotificationRouter:
    """Subscribes providers to event types and forwards events into them.

    Usage::

        router = NotificationRouter()
        router.register(provider, event_type="workflow.completed")
        router.install()

    ``provider`` receives the :class:`DomainEvent` and is responsible for
    building/sending its own :class:`Notification`.
    """

    def __init__(self, dispatcher: EventDispatcher | None = None) -> None:
        self._dispatcher = dispatcher if dispatcher is not None else default_dispatcher
        self._entries: list[tuple[str, NotificationProvider]] = []
        self._unsubscribes: list[Callable[[], None]] = []

    def register(self, provider: NotificationProvider, *, event_type: str) -> None:
        """Route ``event_type`` events to ``provider`` inside this router."""
        if not isinstance(provider, NotificationProvider):
            raise TypeError("provider must be a NotificationProvider.")
        self._entries.append((event_type, provider))

    def install(self) -> None:
        """Subscribe this router to every registered event type."""
        if self._unsubscribes:
            return
        for event_type, provider in self._entries:
            unsubscribe = self._dispatcher.subscribe(event_type, self._dispatch(provider))
            self._unsubscribes.append(unsubscribe)

    def _dispatch(self, provider: NotificationProvider) -> Callable[[DomainEvent], None]:
        def handle(event: DomainEvent) -> None:
            try:
                provider.send(event)
            except Exception:  # noqa: BLE001 - provider failures are isolated
                logger.exception("Notification provider failed for event '%s'.", event.type)

        return handle

    def uninstall(self) -> None:
        """Remove every subscription created by :meth:`install`."""
        for unsubscribe in reversed(self._unsubscribes):
            unsubscribe()
        self._unsubscribes.clear()

    def clear(self) -> None:
        """Unsubscribe and drop all registered providers."""
        self.uninstall()
        self._entries.clear()
