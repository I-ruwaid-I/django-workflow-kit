"""Structured observability for workflow events (Phase 12).

Two orthogonal concerns live here:

* **Structured event logging** — a :class:`StructuredEventLogger` subscribes to
  the existing domain event dispatcher and records each ``DomainEvent`` as a
  structured log record whose ``workflow_event`` extra carries a JSON-friendly
  payload (event, workflow, version, execution, object, states, actor,
  correlation id). This reuses the Phase 5 event stream — it is not a second
  event system.

* **Correlation ids** — a :class:`contextvars.ContextVar`-backed identifier
  that can be set per request or per operation and is embedded in the
  structured records it produces, letting logs from a REST request, its
  notifications, webhooks and audit trail be correlated.

Neither concern changes workflow behaviour or writes to the database.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from workflow_kit.events.types import DomainEvent

logger = logging.getLogger("workflow_kit")

_CORRELATION_ID: ContextVar[str | None] = ContextVar("workflow_kit_correlation_id", default=None)


# -- Correlation ids ----------------------------------------------------------


def current_correlation_id() -> str | None:
    """Return the correlation id active in the current context, if any."""
    return _CORRELATION_ID.get()


def set_correlation_id(value: str) -> Token[str | None]:
    """Set the active correlation id and return the reset token.

    Restore the previous value with :func:`reset_correlation_id`.
    """
    return _CORRELATION_ID.set(value)


def reset_correlation_id(token: Token[str | None]) -> None:
    """Restore the correlation context captured in ``token``."""
    _CORRELATION_ID.reset(token)


@contextmanager
def correlation_id(value: str | None = None) -> Iterator[str]:
    """Enter a :func:`contextvars` scope carrying ``value`` (generated when None).

    Example::

        with correlation_id():
            execution.transition("approve", user=user)
    """
    active = value if value is not None else uuid4().hex
    token = _CORRELATION_ID.set(active)
    try:
        yield active
    finally:
        _CORRELATION_ID.reset(token)


# -- Structured event logging --------------------------------------------------


class StructuredEventLogger:
    """An event-dispatcher observer that logs every event as a structured record.

    ``provider`` is an optional callable returning the correlation id to embed;
    it defaults to the :func:`current_correlation_id` context value.
    """

    def __init__(
        self,
        *,
        log: logging.Logger = logger,
        correlation_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self._log = log
        self._correlation = correlation_provider or current_correlation_id

    def handle(self, event: DomainEvent) -> None:
        """Log ``event`` as a structured record (no-op guard included)."""
        payload = {
            "event": str(event.type),
            "workflow": event.workflow,
            "version": event.workflow_version,
            "execution_id": event.execution_id,
            "object_type": event.object.scope(),
            "object_id": event.object.pk,
            "source_state": event.source_state or None,
            "target_state": event.target_state or None,
            "action": event.action or None,
            "actor": event.actor,
            "correlation_id": self._correlation() or None,
        }
        self._log.info("workflow event: %s", event.type, extra={"workflow_event": payload})

    def __call__(self, event: DomainEvent) -> None:
        self.handle(event)


_installed: StructuredEventLogger | None = None


def install_structured_logging(
    *,
    log: logging.Logger | None = None,
    correlation_provider: Callable[[], str | None] | None = None,
) -> StructuredEventLogger:
    """Subscribe a structured logger to the default event dispatcher.

    Idempotent: calling it more than once returns the already-installed logger
    instead of double-subscribing. Returns the active logger, which can be
    removed later with :func:`uninstall_structured_logging`.
    """
    global _installed
    if _installed is not None:
        return _installed
    from workflow_kit.events import ALL_EVENTS, default_dispatcher

    observer = StructuredEventLogger(
        log=log if log is not None else logger,
        correlation_provider=correlation_provider,
    )
    # Reaching into the observer for the unsubscribe callable would couple the
    # public API to dispatcher internals; we store the unsubscribe alongside.
    _installed = observer
    dispatcher_subscriptions.append(default_dispatcher.subscribe(ALL_EVENTS, observer.handle))
    return observer


dispatcher_subscriptions: list[Callable[[], None]] = []


def uninstall_structured_logging() -> bool:
    """Remove the structured logger from the event dispatcher.

    Returns ``True`` when something was uninstalled.
    """
    global _installed
    if _installed is None:
        return False
    for unsubscribe in dispatcher_subscriptions:
        unsubscribe()
    dispatcher_subscriptions.clear()
    _installed = None
    return True
