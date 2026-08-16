"""Safe condition evaluation for automation rules.

Conditions are data, not code: each clause is ``{field, op, value}`` where
``field`` is a dot-path into a plain dict context. There is no ``eval`` and no
arbitrary attribute access; missing fields simply fail the clause.
"""

from __future__ import annotations

from typing import Any

_OPS = {
    "eq": lambda a, b: _coerce(a) == _coerce(b),
    "ne": lambda a, b: _coerce(a) != _coerce(b),
    "gt": lambda a, b: _coerce(a) > _coerce(b),
    "gte": lambda a, b: _coerce(a) >= _coerce(b),
    "lt": lambda a, b: _coerce(a) < _coerce(b),
    "lte": lambda a, b: _coerce(a) <= _coerce(b),
    "contains": lambda a, b: str(a or "") and _coerce(b) in _coerce_list(a),
    "startswith": lambda a, b: str(a or "").lower().startswith(str(b).lower()),
    "endswith": lambda a, b: str(a or "").lower().endswith(str(b).lower()),
    "is_empty": lambda a, b: _is_empty(a),
    "not_empty": lambda a, b: not _is_empty(a),
}


def _coerce(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return str(value or "").lower()


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if value is None:
        return []
    return [value]


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _lookup(context: dict[str, Any], path: str) -> Any:
    node: Any = context
    for part in path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def clause_passes(clause: dict[str, Any], context: dict[str, Any]) -> bool:
    """Evaluate one ``{field, op, value}`` clause against ``context``."""
    if not isinstance(clause, dict):
        return True
    field = clause.get("field")
    op = clause.get("op") or "eq"
    expected = clause.get("value")
    if not field:
        return True
    actual = _lookup(context, field)
    fn = _OPS.get(op)
    if fn is None:
        return False
    try:
        return bool(fn(actual, expected))
    except (TypeError, ValueError):
        return False


def conditions_met(conditions: list[dict[str, Any]], context: dict[str, Any]) -> bool:
    """All clauses must pass; an empty clause list is always true."""
    return all(clause_passes(c, context) for c in conditions)
