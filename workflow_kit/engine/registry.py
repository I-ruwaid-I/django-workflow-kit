"""Workflow definition registry.

A lightweight, read-only-after-registration registry mapping workflow names to
``Workflow`` definitions. It mirrors Django's registry conventions and lets
any code resolve a workflow definition from a persisted execution without
knowing where the definition lives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from workflow_kit.exceptions import WorkflowConfigurationError, WorkflowNotFoundError

if TYPE_CHECKING:
    from workflow_kit.engine.workflow import Workflow

_WORKFLOWS: dict[str, Workflow] = {}


def register(workflow: Workflow) -> None:
    """Register a workflow definition under its name.

    Raises :class:`WorkflowConfigurationError` if a workflow with the same name
    is already registered.
    """
    if workflow.name in _WORKFLOWS:
        raise WorkflowConfigurationError(
            f"A workflow named '{workflow.name}' is already registered."
        )
    _WORKFLOWS[workflow.name] = workflow


def get_workflow(name: str) -> Workflow:
    """Return the registered workflow with the given name.

    Raises :class:`WorkflowNotFoundError` if no such workflow is registered.
    """
    try:
        return _WORKFLOWS[name]
    except KeyError as exc:
        raise WorkflowNotFoundError(f"No workflow named '{name}' is registered.") from exc


def unregister(name: str) -> None:
    """Remove a previously registered workflow (mainly useful in tests)."""
    _WORKFLOWS.pop(name, None)


def all_workflows() -> tuple[Workflow, ...]:
    """Return all registered workflows in registration order."""
    return tuple(_WORKFLOWS.values())
