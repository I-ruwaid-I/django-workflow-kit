"""Automation engine: turn events into rule evaluations.

A single event dispatcher handler is subscribed to every domain event. For
each enabled :class:`~workflow_kit.models.automation.AutomationRule` whose
``trigger`` matches the event type, the engine builds a context from the event,
checks the rule's conditions and runs its actions.

Host applications can also call :func:`fire` directly with a raw event name
and payload so automation runs on facts that are not workflow events (e.g. a
survey response being submitted).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from workflow_kit.automation.actions import get as get_action
from workflow_kit.automation.evaluate import conditions_met

if TYPE_CHECKING:
    from workflow_kit.events.types import DomainEvent
    from workflow_kit.models.automation import AutomationRule

logger = logging.getLogger(__name__)

# Guards against double subscription when AppConfig.ready() runs more than once
# (e.g. across test classes).
_installed = False


def install():
    """Subscribe the automation hook to the default event dispatcher (once)."""
    global _installed
    if _installed:
        return
    from workflow_kit.events.dispatcher import ALL_EVENTS, default_dispatcher

    default_dispatcher.subscribe(ALL_EVENTS, on_event)
    _installed = True


def context_for_event(event: DomainEvent) -> dict[str, Any]:
    """Flatten a domain event into the plain dict used for conditions/actions."""
    return {
        "event": event.type,
        "workflow": event.workflow,
        "execution_id": event.execution_id,
        "actor": event.actor,
        "source_state": event.source_state,
        "target_state": event.target_state,
        "action": event.action,
        "payload": event.metadata or {},
        "object": event.object.to_dict() if event.object else {},
    }


def fire(trigger: str, context: dict[str, Any], scope: str = "") -> int:
    """Run every enabled rule matching ``trigger`` against ``context``.

    ``scope`` narrows the match: when provided, only rules whose scope equals
    it or is blank run. Returns how many rules fired. Handler and evaluation
    errors are logged and isolated — automation must never crash the calling
    code path.
    """
    from workflow_kit.models import AutomationRule

    fired = 0
    try:
        rules = AutomationRule.objects.filter(enabled=True, trigger=trigger)
    except Exception:  # pragma: no cover - DB unavailable
        logger.exception("Automation: could not load rules for %r", trigger)
        return 0
    for rule in rules:
        if scope and rule.scope and rule.scope != scope:
            continue
        try:
            if not conditions_met(rule.condition, context):
                continue
            _run_actions(rule, context)
            fired += 1
        except Exception:  # noqa: BLE001 - fault-isolated on purpose
            logger.exception("Automation rule %r failed", rule.name)
    return fired


def on_event(event: DomainEvent) -> None:
    """Event dispatcher hook: evaluate rules for the event's type."""
    fire(str(event.type), context_for_event(event))


def _run_actions(rule: AutomationRule, context: dict[str, Any]) -> None:
    for item in rule.actions or []:
        if not isinstance(item, dict):
            continue
        handler = get_action(item.get("action"))
        if handler is None:
            logger.warning(
                "Automation rule %r references unregistered action %r",
                rule.name,
                item.get("action"),
            )
            continue
        handler(context, item.get("params") or {})
