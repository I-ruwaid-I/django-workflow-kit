"""Built-in, safe conditions for restricting transitions.

These conditions evaluate a single field (optionally a dotted path such as
``customer.is_verified``) on the workflow's business object. They use ordinary
attribute access and Python comparisons only — there is no ``eval`` of
user-provided code.
"""

from __future__ import annotations

from typing import Any

from workflow_kit.conditions.base import Condition
from workflow_kit.exceptions import ConditionEvaluationError


def resolve_field(context: Any, field: str) -> Any:
    """Resolve ``field`` (possibly "dotted") against the workflow object.

    Raises :class:`~workflow_kit.exceptions.ConditionEvaluationError` when the
    object does not expose the requested attribute, so failures are explicit.
    """
    value = getattr(context, "object", None)
    for part in field.split("."):
        try:
            value = getattr(value, part)
        except AttributeError as exc:
            raise ConditionEvaluationError(
                f"Condition field '{field}' is not available on "
                f"{type(getattr(context, 'object', None)).__name__ or 'object'}."
            ) from exc
    return value


class FieldEquals(Condition):
    """Pass when ``context.object.<field> == value``."""

    def __init__(self, field: str, value: Any) -> None:
        self.field = field
        self.value = value

    def evaluate(self, context: Any) -> bool:
        return bool(resolve_field(context, self.field) == self.value)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.field!r} == {self.value!r})"


class FieldNotEquals(Condition):
    """Pass when ``context.object.<field> != value``."""

    def __init__(self, field: str, value: Any) -> None:
        self.field = field
        self.value = value

    def evaluate(self, context: Any) -> bool:
        return bool(resolve_field(context, self.field) != self.value)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.field!r} != {self.value!r})"


class _Comparison(Condition):
    """Base for numeric/string ordering comparisons."""

    def __init__(self, field: str, value: Any) -> None:
        self.field = field
        self.value = value

    def _compare(self, actual: Any) -> bool:
        raise NotImplementedError

    def evaluate(self, context: Any) -> bool:
        return self._compare(resolve_field(context, self.field))

    def __repr__(self) -> str:
        operator = {
            GreaterThan: ">",
            GreaterThanOrEqual: ">=",
            LessThan: "<",
            LessThanOrEqual: "<=",
        }[type(self)]
        return f"{type(self).__name__}({self.field!r} {operator} {self.value!r})"


class GreaterThan(_Comparison):
    """Pass when ``context.object.<field> > value``."""

    def _compare(self, actual: Any) -> bool:
        return bool(actual > self.value)


class GreaterThanOrEqual(_Comparison):
    """Pass when ``context.object.<field> >= value``."""

    def _compare(self, actual: Any) -> bool:
        return bool(actual >= self.value)


class LessThan(_Comparison):
    """Pass when ``context.object.<field> < value``."""

    def _compare(self, actual: Any) -> bool:
        return bool(actual < self.value)


class LessThanOrEqual(_Comparison):
    """Pass when ``context.object.<field> <= value``."""

    def _compare(self, actual: Any) -> bool:
        return bool(actual <= self.value)


class IsTrue(Condition):
    """Pass when ``context.object.<field> is True`` (e.g. a boolean field)."""

    def __init__(self, field: str) -> None:
        self.field = field

    def evaluate(self, context: Any) -> bool:
        return resolve_field(context, self.field) is True

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.field!r})"


class IsFalse(Condition):
    """Pass when ``context.object.<field> is False``."""

    def __init__(self, field: str) -> None:
        self.field = field

    def evaluate(self, context: Any) -> bool:
        return resolve_field(context, self.field) is False

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.field!r})"
