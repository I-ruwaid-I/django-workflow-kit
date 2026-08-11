"""Shared helpers for the workflow REST API.

Kept separate from the serializers so the action-introspection logic (which
relies on the engine's authorization and condition evaluation) stays a thin
wrapper over the existing engine rather than a parallel implementation.
"""

from __future__ import annotations

from typing import Any

from workflow_kit.models import WorkflowExecution


def available_actions(
    execution: WorkflowExecution,
    user: Any = None,
) -> list[dict[str, str]]:
    """Return the actions available to ``user`` as ``{"name", "label"}`` dicts.

    Authorization and conditions are resolved by the engine exactly as the
    Python API does — the REST layer never re-implements them.
    """
    result: list[dict[str, str]] = []
    workflow = execution.workflow
    for name in workflow.available_actions(execution, user=user):
        transition = workflow.transition_for(execution.current_state, name)
        result.append({"name": name, "label": transition.label if transition else name})
    return result
