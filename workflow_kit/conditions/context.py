"""The controlled context handed to conditions.

Conditions never see unrestricted globals or raw request objects; they receive
exactly the fields defined here. The business object is always fetched fresh
from the database so conditions are evaluated against persisted (normalized)
values, never a possibly-in-memory, unnormalized instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ObjectDoesNotExist


@dataclass(frozen=True)
class ConditionContext:
    """Controlled context evaluated by a :class:`~workflow_kit.conditions.base.Condition`.

    ``object`` is a convenience alias for ``execution.object`` — the business
    object the workflow is running against. Applications access its fields
    directly (e.g. ``context.object.amount``).
    """

    user: Any
    workflow: Any
    execution: Any
    object: Any = None


def _persisted_object(execution: Any) -> Any:
    """Return a fresh copy of the execution's business object from the DB.

    Falls back to the ORM ``execution.object`` when the object can no longer be
    found, which keeps introspection working after the row was deleted.
    """
    content_type = getattr(execution, "content_type", None)
    object_id = getattr(execution, "object_id", None)
    model = getattr(content_type, "model_class", lambda: None)()
    if model is not None and object_id is not None:
        try:
            return model._base_manager.get(pk=object_id)
        except (ObjectDoesNotExist, ValueError):
            return None
    return getattr(execution, "object", None)


def build_condition_context(workflow: Any, execution: Any, user: Any = None) -> ConditionContext:
    """Build the context used to evaluate conditions for ``execution``."""
    return ConditionContext(
        user=user,
        workflow=workflow,
        execution=execution,
        object=_persisted_object(execution),
    )
