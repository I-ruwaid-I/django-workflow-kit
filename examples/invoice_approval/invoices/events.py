"""Demo event wiring.

This module lives in the demo on purpose: it shows how an application consumes
the domain events emitted by the engine. It subscribes a console logger
(``[EVENT]`` lines) and an email notification for completed workflows. None of
this ships inside ``workflow_kit`` — it is pure application-side demonstration
code.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from workflow_kit import EventType
from workflow_kit.events import ALL_EVENTS, subscribe
from workflow_kit.notifications import EmailProvider

if TYPE_CHECKING:
    from workflow_kit.events.types import DomainEvent

logger = logging.getLogger(__name__)

_installed = False


def _log_event(event: DomainEvent) -> None:
    """Print a readable ``[EVENT]`` line for every workflow event."""
    transition = ""
    if event.source_state and event.target_state:
        transition = f" From: {event.source_state} To: {event.target_state}"
    actor = f" Actor: {event.actor}" if event.actor else ""
    logger.info("[EVENT] %s Invoice: %s%s%s", event.type, event.object.display, transition, actor)


def _notify_completed(event: DomainEvent) -> None:
    """Send a demo email when a workflow completes."""
    provider = EmailProvider(recipients=lambda _event: ["demo@example.invalid"])
    try:
        provider.send(event)
    except Exception:  # noqa: BLE001 - demo should degrade gracefully
        logger.warning("Demo email notification failed.", exc_info=True)


def install() -> None:
    """Subscribe the demo handlers (idempotent, safe to call repeatedly)."""
    global _installed
    if _installed:
        return
    _installed = True
    subscribe(ALL_EVENTS, _log_event)
    subscribe(str(EventType.WORKFLOW_COMPLETED), _notify_completed)
