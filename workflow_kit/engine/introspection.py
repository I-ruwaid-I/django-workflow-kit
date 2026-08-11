"""Introspection helpers for workflow definitions.

Phase 11 adds developer-facing tooling: a JSON-safe dump of a workflow, graph
reachability analysis (which states are reachable from the initial state) and
enumeration of simple paths through the state machine. These helpers are pure
Python — they work on a :class:`~workflow_kit.engine.workflow.Workflow`
definition and never touch the database.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import Any

from workflow_kit.engine.versioning import _encode_value
from workflow_kit.engine.workflow import State, Transition, Workflow


def _transition_to_dict(transition: Transition) -> dict[str, Any]:
    """Presentable, JSON-safe description of a single transition."""
    condition_summary = [type(condition).__name__ for condition in transition.conditions]
    return {
        "name": transition.name,
        "label": transition.label,
        "source": transition.source,
        "target": transition.target,
        "permission": transition.permission,
        "conditions": condition_summary,
    }


def workflow_to_dict(workflow: Workflow) -> dict[str, Any]:
    """Return a presentable, JSON-safe dump of ``workflow``.

    Unlike :func:`workflow_kit.engine.versioning.serialize_workflow`, which
    produces a storable *snapshot*, this describes the live definition for
    humans and the CLI: it includes derived labels, reachability and terminal
    flags and always serializes (custom conditions are described by python
    class name rather than raised on).
    """
    initial = workflow.initial
    reachable = reachable_states(workflow)
    states: list[dict[str, Any]] = []
    for state in workflow.states:
        states.append(
            {
                "name": state.name,
                "label": state.label,
                "initial": state.name == initial,
                "terminal": workflow.is_terminal(state.name),
                "reachable": state.name in reachable,
                "actions": workflow.actions_from(state.name),
            }
        )
    transitions = [_transition_to_dict(t) for t in _all_transitions(workflow)]

    approval_requirements: dict[str, Any] = {}
    for state_name, requirement in workflow.approval_requirements.items():
        approval_requirements[state_name] = {
            "mode": requirement.mode,
            "approvers": [str(item) for item in requirement.approvers],
            "quorum": requirement.quorum,
            "allow_self": requirement.allow_self,
            "sla": _encode_value(requirement.sla),
            "label": requirement.label,
        }
    return {
        "name": workflow.name,
        "initial": initial,
        "states": states,
        "transitions": transitions,
        "approval_requirements": approval_requirements,
        "metrics": {
            "state_count": len(states),
            "transition_count": len(transitions),
            "terminal_count": len(workflow.terminal_states),
            "reachable_state_count": len(reachable),
            "unreachable_state_count": len(states) - len(reachable),
        },
    }


def _all_transitions(workflow: Workflow) -> list[Transition]:
    """Every transition in definition order, without duplicates."""
    ordered: list[Transition] = []
    seen: set[tuple[str, str, str]] = set()
    for state in workflow.states:
        for transition in workflow.transitions_from(state.name):
            key = (transition.source, transition.name, transition.target)
            if key not in seen:
                seen.add(key)
                ordered.append(transition)
    return ordered


def reachable_states(workflow: Workflow, start: str | None = None) -> set[str]:
    """Return the names of all states reachable from the initial state.

    A BFS over the state graph; every state reached by walking transitions
    from validation, in definition order, is returned.
    """
    start = start if start is not None else workflow.initial
    visited: set[str] = set()
    queue: deque[str] = deque([start])
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for transition in workflow.transitions_from(current):
            if transition.target not in visited:
                queue.append(transition.target)
    return visited


def unreachable_states(workflow: Workflow) -> list[str]:
    """Return the names of declared states that can never be entered, in order."""
    reachable = reachable_states(workflow)
    return [state.name for state in workflow.states if state.name not in reachable]


def outgoing_transitions(workflow: Workflow, state_name: str) -> list[Transition]:
    """All transitions leaving ``state_name`` (definition order)."""
    return workflow.transitions_from(state_name)


def condition_variants(workflow: Workflow, source: str, action: str) -> list[Transition]:
    """All transitions for ``action`` from ``source``.

    Conditional routing means a single action may resolve to several targets;
    this exposes all candidate transitions for a source/action pair.
    """
    return workflow.transitions_for_action(source, action)


# -- Path enumeration ---------------------------------------------------------


def simple_paths(
    workflow: Workflow,
    start: str | None = None,
    end: str | None = None,
    *,
    max_length: int = 32,
) -> list[list[Transition]]:
    """Enumerate every simple (cycle-free) path through the workflow.

    ``end`` defaults to any of the workflow's terminal states. A simple path is
    a sequence of transitions that never revisits a state, so enumeration is
    guaranteed to terminate. Paths longer than ``max_length`` are dropped.
    """
    if max_length < 1:
        return []
    start = start if start is not None else workflow.initial
    paths: list[list[Transition]] = []
    _walk_simple(
        workflow,
        start,
        end,
        max_length,
        visited={start},
        current=[],
        paths=paths,
    )
    return paths


def _walk_simple(
    workflow: Workflow,
    current_state: str,
    end: str | None,
    max_length: int,
    *,
    visited: set[str],
    current: list[Transition],
    paths: list[list[Transition]],
) -> None:
    if end is None and workflow.is_terminal(current_state):
        paths.append(list(current))
        return
    if end is not None and current_state == end:
        paths.append(list(current))
        return
    if len(current) >= max_length:
        return
    for transition in workflow.transitions_from(current_state):
        if transition.target in visited:
            continue
        visited.add(transition.target)
        current.append(transition)
        _walk_simple(
            workflow,
            transition.target,
            end,
            max_length,
            visited=visited,
            current=current,
            paths=paths,
        )
        current.pop()
        visited.discard(transition.target)


def path_states(path: Sequence[Transition], start: str) -> list[str]:
    """Return the list of state names visited by ``path``, starting at ``start``."""
    states = [start]
    for transition in path:
        states.append(transition.target)
    return states


# -- State helpers ------------------------------------------------------------


def state_display(workflow: Workflow, state: State) -> str:
    """Render ``state`` as ``"name (label)"`` for CLI output."""
    return f"{state.name} ({state.label})"
