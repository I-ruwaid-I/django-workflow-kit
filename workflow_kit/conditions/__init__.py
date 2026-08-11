"""Condition system for restricting workflow transitions.

Conditions are explicit, safe Python objects evaluated against a controlled
:class:`ConditionContext`. They gate both introspection
(``can_transition`` / ``available_actions``) and the actual transition, which
re-evaluates them at execution time. Arbitrary user-supplied code is never
executed.
"""

from workflow_kit.conditions.base import Condition
from workflow_kit.conditions.builtin import (
    FieldEquals,
    FieldNotEquals,
    GreaterThan,
    GreaterThanOrEqual,
    IsFalse,
    IsTrue,
    LessThan,
    LessThanOrEqual,
)
from workflow_kit.conditions.context import ConditionContext, build_condition_context
from workflow_kit.conditions.evaluate import conditions_met
from workflow_kit.conditions.logical import All, Any, Not

__all__ = [
    "Condition",
    "ConditionContext",
    "build_condition_context",
    "conditions_met",
    "FieldEquals",
    "FieldNotEquals",
    "GreaterThan",
    "GreaterThanOrEqual",
    "IsTrue",
    "IsFalse",
    "LessThan",
    "LessThanOrEqual",
    "All",
    "Any",
    "Not",
]
