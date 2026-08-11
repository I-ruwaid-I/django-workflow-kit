"""The extensible condition interface for Django Workflow Kit.

Conditions restrict *when* a transition may run by evaluating a controlled
context. Applications implement :class:`Condition` to express custom rules
(``amount > 10000``, ``customer.is_verified``, ...) without modifying the
workflow engine.

Security: conditions are never defined or parsed from arbitrary user input.
There is no ``eval`` / ``exec`` path anywhere in the conditions system; every
condition is an explicit Python object evaluated safely against a fixed
:class:`~workflow_kit.conditions.context.ConditionContext`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Condition(ABC):
    """Interface for a reusable condition.

    Subclass and implement :meth:`evaluate` to decide whether the current
    ``context`` satisfies the condition:

    .. code-block:: python

        class LargeInvoice(Condition):
            def evaluate(self, context) -> bool:
                return context.object.amount > Decimal("10000")
    """

    @abstractmethod
    def evaluate(self, context: Any) -> bool:
        """Return True when ``context`` satisfies this condition."""
        raise NotImplementedError
