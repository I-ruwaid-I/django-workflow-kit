"""Notification providers base layer.

Notifications are built on top of events: a provider turns a domain event into
a :class:`Notification`, then delivers it. The engine never calls a provider
directly — it only emits events and the router forwards them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from workflow_kit.events.types import DomainEvent


@dataclass(frozen=True)
class Notification:
    """A structured message to deliver.

    Providers build ``Notification`` objects from events. ``recipients`` names
    who should receive it (emails, user identifiers, webhook ids...),
    ``subject``/``body`` are the message bodies and ``context`` carries the
    data the message renders from.
    """

    event: DomainEvent
    recipients: tuple[str, ...]
    subject: str = ""
    body: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def event_type(self) -> str:
        """The domain event type that produced this notification."""
        return str(self.event.type)


class NotificationProvider(ABC):
    """Base class for concrete notification channels.

    Providers receive raw events and deliver a :class:`Notification`.
    """

    @abstractmethod
    def send(self, event: DomainEvent) -> bool:
        """Build and deliver a notification for ``event``.

        Return True on success. Providers that cannot deliver should raise a
        :class:`NotificationError`.
        """


class NotificationError(Exception):
    """Raised when a provider cannot deliver a notification."""
