"""Logical composition helpers for conditions.

Build richer rules without a full expression language:

.. code-block:: python

    All(GreaterThan("amount", 100), FieldEquals("currency", "USD"))
    Any(IsTrue("customer.is_verified"), FieldEquals("priority", "high"))
    Not(LessThan("amount", 10_000))
"""

from __future__ import annotations

from workflow_kit.conditions.base import Condition
from workflow_kit.exceptions import WorkflowConfigurationError


class CompositeCondition(Condition):
    """Base for conditions built from other conditions."""

    def __init__(self, *conditions: Any) -> None:
        children = conditions
        if len(children) == 1 and isinstance(children[0], (list, tuple)):
            children = tuple(children[0])
        for condition in children:
            if not isinstance(condition, Condition):
                raise WorkflowConfigurationError(
                    f"{type(self).__name__} requires Condition instances, got {condition!r}."
                )
        self.conditions: tuple[Condition, ...] = children

    def __repr__(self) -> str:
        return f"{type(self).__name__}({', '.join(repr(c) for c in self.conditions)})"


class All(CompositeCondition):
    """Pass when **every** child condition passes (logical AND)."""

    def evaluate(self, context: Any) -> bool:
        return all(condition.evaluate(context) for condition in self.conditions)


class Any(CompositeCondition):
    """Pass when **at least one** child condition passes (logical OR)."""

    def evaluate(self, context: Any) -> bool:
        return any(condition.evaluate(context) for condition in self.conditions)


class Not(CompositeCondition):
    """Pass when exactly one child condition **fails** (logical NOT)."""

    def evaluate(self, context: Any) -> bool:
        if len(self.conditions) != 1:
            raise WorkflowConfigurationError(
                f"{type(self).__name__} requires exactly one condition."
            )
        return not self.conditions[0].evaluate(context)
