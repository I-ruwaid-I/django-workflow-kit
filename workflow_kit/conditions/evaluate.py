"""Safe evaluation helpers for transition conditions.

The engine calls :func:`conditions_met` to gate both the read-only checks
(``can_transition`` / ``available_actions``) and the actual transition, so a
condition is always re-evaluated against fresh state at execution time.
"""

from __future__ import annotations

from typing import Any


def conditions_met(transition: Any, context: Any) -> bool:
    """Return True when every condition on ``transition`` passes.

    A ``ConditionConditional`` child evaluation error (for example a missing
    attribute) propagates as
    :class:`~workflow_kit.exceptions.ConditionEvaluationError`.
    """
    for condition in getattr(transition, "conditions", None) or ():
        if not condition.evaluate(context):
            return False
    return True
