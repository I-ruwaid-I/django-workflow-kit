"""Dry-run simulation of workflow executions.

Phase 11's simulation engine replays a
:class:`~workflow_kit.engine.workflow.Workflow` definition without touching the
database or running side effects. It lets developers answer questions such as
"does every path from the initial state reach a terminal state?" and "what
happens when I apply submit, approve?" before wiring ORM objects.

Simulation operates purely on the definition: conditions are not evaluated
(they depend on a live business object); instead each transition may be *gated*
by an optional predicate so callers can model "condition passes / fails".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from workflow_kit.engine.introspection import simple_paths
from workflow_kit.engine.workflow import Transition, Workflow
from workflow_kit.exceptions import (
    InvalidTransitionError,
    NoPathFoundError,
    SimulationError,
)

Gate = Callable[[Transition], bool]


def _default_gate(_transition: Transition) -> bool:
    """Default condition gate: every transition's conditions pass."""
    return True


_DEFAULT_GATE: Gate = _default_gate


@dataclass(frozen=True)
class SimStep:
    """One simulated transition application."""

    action: str
    source: str
    target: str

    def __str__(self) -> str:
        return f"{self.action}: {self.source} -> {self.target}"


@dataclass
class SimulationResult:
    """The outcome of one dry-run.

    ``steps`` lists every transition applied in order; ``states`` tracks the
    state names entered (starting with ``start``). ``terminal`` is the final
    state reached (the last state when the run stopped), ``completed`` is True
    when that state is terminal and ``blocked`` reports the first action that
    could not be run, if any.
    """

    workflow_name: str
    start: str
    steps: list[SimStep] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    blocked: str | None = None

    @property
    def terminal(self) -> str:
        """The final simulated state (the last visited state)."""
        return self.states[-1] if self.states else self.start

    @property
    def completed(self) -> bool:
        """True when the run reached a terminal state."""
        return self.blocked is None and bool(self.states)


def _resolve_target(
    workflow: Workflow,
    current: str,
    action: str,
    gate: Gate,
) -> Transition:
    """Pick the transition for ``action``, applying the condition gate."""
    candidates = workflow.transitions_for_action(current, action)
    if not candidates:
        raise InvalidTransitionError(
            f"Cannot execute transition '{action}': current state is '{current}' "
            f"in workflow '{workflow.name}'.",
            workflow=workflow.name,
            state=current,
            action=action,
        )
    passing = [t for t in candidates if gate(t)]
    if not passing:
        raise InvalidTransitionError(
            f"Transition '{action}' is blocked by conditions in state '{current}' "
            f"of workflow '{workflow.name}'.",
            workflow=workflow.name,
            state=current,
            action=action,
        )
    if len(passing) > 1:
        targets = ", ".join(t.target for t in passing)
        raise SimulationError(
            f"Transition '{action}' from '{current}' resolves to multiple passing "
            f"targets ({targets}) under the simulation gate; provide a gate that "
            f"selects exactly one.",
            workflow=workflow.name,
            state=current,
            action=action,
        )
    return passing[0]


def simulate(
    workflow: Workflow,
    actions: list[str] | tuple[str, ...],
    *,
    start: str | None = None,
    gate: Gate | None = None,
    max_steps: int = 100,
) -> SimulationResult:
    """Replay ``actions`` against ``workflow`` and return the simulation result.

    ``start`` defaults to the workflow's initial state. ``gate`` optionally
    decides whether each transition's conditions pass (defaults to "always
    passes"). Simulation stops early — without raising — when an action cannot
    be run; ``result.blocked`` names the offending action. A runaway loop is
    guarded by ``max_steps``.
    """
    gate = gate or _DEFAULT_GATE
    current = start if start is not None else workflow.initial
    result = SimulationResult(workflow_name=workflow.name, start=current)
    result.states = [current]
    for action in actions:
        if len(result.states) - 1 >= max_steps:
            result.blocked = action
            break
        try:
            transition = _resolve_target(workflow, current, action, gate)
        except (InvalidTransitionError, SimulationError):
            result.blocked = action
            break
        result.steps.append(
            SimStep(action=action, source=transition.source, target=transition.target)
        )
        current = transition.target
        result.states.append(current)
    return result


def simulate_all(
    workflow: Workflow,
    *,
    start: str | None = None,
    max_length: int = 32,
) -> list[SimulationResult]:
    """Simulate every simple path from ``start`` to a terminal state.

    Uses the same cycle-free path enumeration as
    :func:`workflow_kit.engine.introspection.simple_paths`, so the return list
    is finite and each path's actions are derived from its transitions.
    """
    start = start if start is not None else workflow.initial
    results: list[SimulationResult] = []
    for path in simple_paths(workflow, start=start, max_length=max_length):
        result = SimulationResult(workflow_name=workflow.name, start=start)
        result.states = [start]
        for transition in path:
            result.steps.append(
                SimStep(
                    action=transition.name,
                    source=transition.source,
                    target=transition.target,
                )
            )
            result.states.append(transition.target)
        results.append(result)
    return results


def verify_always_completes(
    workflow: Workflow,
    *,
    start: str | None = None,
) -> None:
    """Raise :class:`NoPathFoundError` when every path cannot reach a terminal state.

    Static check: every state reachable from ``start`` (default initial state)
    must itself be able to reach a terminal state. A dead end (a non-terminal
    state with no way onward) and a closed cycle that can never exit both fail
    this check and raise :class:`~workflow_kit.exceptions.NoPathFoundError`.
    """
    start = start if start is not None else workflow.initial
    terminal = workflow.terminal_states
    reachable = _forward_reachable(workflow, start)
    for state in sorted(reachable):
        if state in terminal:
            continue
        if not (_forward_reachable(workflow, state) & terminal):
            raise NoPathFoundError(
                f"Workflow '{workflow.name}' does not always complete: state "
                f"'{state}' is a dead end (no path to a terminal state).",
                workflow=workflow.name,
                state=state,
            )


def _forward_reachable(workflow: Workflow, start: str) -> set[str]:
    """Names of all states reachable from ``start`` by any transition path."""
    from workflow_kit.engine.introspection import reachable_states

    return reachable_states(workflow, start=start)
