"""Deterministic workflow fixtures for tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from workflow_kit.engine import registry
from workflow_kit.engine.workflow import Workflow


def workflow_factory(
    name: str,
    *,
    initial: str = "draft",
    states: Sequence[str] | None = None,
    transitions: Sequence[Any] | None = None,
    register: bool = True,
) -> Workflow:
    """Build a deterministic workflow for tests.

    Defaults model an invoice-approval style flow:

    - states: ``draft -> review -> approved`` plus ``rejected``
    - transitions: ``submit`` (draft->review), ``approve`` (review->approved),
      ``reject`` (review->rejected)

    Keyword arguments override the defaults, so ``workflow_factory("wf")`` and
    ``workflow_factory("wf", transitions=[("go", "a", "b")], states=["a", "b"],
    initial="a")`` are both valid. ``register=True`` (default) registers under
    ``name``; the caller is responsible for unregistering if used repeatedly.
    """
    if states is None:
        states = ["draft", "review", "approved", "rejected"]
    if transitions is None:
        transitions = [
            ("submit", "draft", "review"),
            ("approve", "review", "approved"),
            ("reject", "review", "rejected"),
        ]
    return Workflow(
        name=name,
        initial=initial,
        states=states,
        transitions=transitions,
        register=register,
    )


class SimpleWorkflow:
    """A tiny ready-made workflow for smoke tests and examples.

    States ``a -> b -> c`` (``c`` terminal) with a single ``go`` action per
    hop. Instantiate with a name, then start executions with
    :attr:`workflow.start(obj)`.
    """

    def __init__(self, name: str = "simple", *, register: bool = False) -> None:
        self.name = name
        self.workflow = workflow_factory(
            name,
            initial="a",
            states=["a", "b", "c"],
            transitions=[("go", "a", "b"), ("go", "b", "c")],
            register=register,
        )


def workflow_module() -> list[Workflow]:
    """Return ``[workflow_factory("cli_demo")]`` for deploy-module smoke tests.

    Mirrors a user module exposing ``WORKFLOWS`` so the CLI ``deploy``
    subcommand can be tested against an importable module.
    """
    return [workflow_factory("cli_demo", register=False)]


def unregister_all() -> None:
    """Remove every registered workflow (resets inter-test state)."""
    for workflow in list(registry.all_workflows()):
        registry.unregister(workflow.name)
