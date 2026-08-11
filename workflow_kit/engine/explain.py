"""Explain and why-not diagnostics for workflow actions.

Phase 11 surfaces *why* an action is possible or impossible for a given
execution, complementing the boolean :meth:`Workflow.can_transition` with a
diagnostic :func:`why_not` that reports each blocking factor — structural
(unregistered action, terminal state), authorization and conditional routing.

Everything here is read-only: explaining never mutates an execution. Callers
pass the execution and user exactly as they would to ``transition``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from workflow_kit.conditions.evaluate import conditions_met
from workflow_kit.engine.workflow import Transition, Workflow
from workflow_kit.permissions.evaluate import is_authorized


@dataclass(frozen=True)
class BlockReason:
    """A single reason an action cannot be executed.

    ``kind`` is a stable machine-readable identifier (e.g. ``"no_action"``,
    ``"terminal"``, ``"permission"``, ``"condition"``, ``"ambiguous"``) and
    ``detail`` is a human-readable sentence.
    """

    kind: str
    detail: str
    transition: Transition | None = None


@dataclass
class ActionExplanation:
    """Full explanation of one action for one execution.

    ``applicable`` records whether the action can run; ``reasons`` lists every
    blocking factor found (empty when applicable). ``candidates`` exposes the
    underlying transitions considered and, for condition failures, *which*
    condition blocked each candidate.
    """

    workflow_name: str
    state: str
    action: str
    applicable: bool
    reasons: list[BlockReason] = field(default_factory=list)
    candidates: list[tuple[Transition, bool]] = field(default_factory=list)
    user: Any = None


def _condition_failures(
    transition: Transition,
    context: Any,
) -> list[Any]:
    """Return the conditions of ``transition`` that fail against ``context``."""
    failures = []
    for condition in transition.conditions:
        try:
            passed = condition.evaluate(context)
        except Exception:  # noqa: BLE001 - report instead of aborting the explain
            passed = False
        if not passed:
            failures.append(condition)
    return failures


def _structure_reasons(
    workflow: Workflow,
    state: str,
    action: str,
    candidates: list[Transition],
) -> list[BlockReason]:
    """Reasons that hold regardless of user/object: terminal or unknown action."""
    reasons: list[BlockReason] = []
    if workflow.is_terminal(state):
        reasons.append(
            BlockReason(
                "terminal",
                f"Workflow '{workflow.name}' is in terminal state '{state}'; "
                "no further actions are possible.",
            )
        )
    if not candidates:
        reasons.append(
            BlockReason(
                "no_action",
                f"Action '{action}' does not exist from state '{state}' of "
                f"workflow '{workflow.name}'.",
            )
        )
    return reasons


def why_not(
    workflow: Workflow,
    execution: Any,
    action: str,
    *,
    user: Any = None,
    condition_context: Any = None,
) -> ActionExplanation:
    """Explain why ``action`` cannot be executed on ``execution``.

    ``condition_context`` is the
    :class:`~workflow_kit.conditions.context.ConditionContext` used to evaluate
    conditions; it defaults to the standard context built for ``execution``.
    The returned :class:`ActionExplanation` is never ``applicable``; use
    :func:`explain` for a full verdict on either side.
    """
    explanation = explain(
        workflow,
        execution,
        action,
        user=user,
        condition_context=condition_context,
    )
    return explanation


def explain(
    workflow: Workflow,
    execution: Any,
    action: str,
    *,
    user: Any = None,
    condition_context: Any = None,
) -> ActionExplanation:
    """Explain whether ``action`` can run on ``execution`` for ``user``.

    Structural problems (terminal state, unregistered action) are reported
    directly. Otherwise each candidate transition is checked: the user's
    authorization and, when authorized, its conditions. The action is
    ``applicable`` when exactly one candidate is authorized *and* has all
    conditions passing, mirroring the engine's resolution rules.
    """
    from workflow_kit.conditions.context import build_condition_context

    state = execution.current_state
    context = condition_context or build_condition_context(workflow, execution, user=user)
    candidates = workflow.transitions_for_action(state, action)
    explanation = ActionExplanation(
        workflow_name=workflow.name,
        state=state,
        action=action,
        applicable=False,
        user=user,
    )

    structural = _structure_reasons(workflow, state, action, candidates)
    explanation.reasons.extend(structural)
    if structural:
        return explanation

    passing = []
    for transition in candidates:
        explanation.candidates.append((transition, False))
        if not is_authorized(user, workflow, execution, transition):
            explanation.reasons.append(
                BlockReason(
                    "permission",
                    f"User does not satisfy the permission requirement of "
                    f"transition '{transition.name}' ({transition.permission!r}).",
                    transition,
                )
            )
            continue
        if not conditions_met(transition, context):
            failures = _condition_failures(transition, context)
            names = ", ".join(type(c).__name__ for c in failures) or "a condition"
            explanation.reasons.append(
                BlockReason(
                    "condition",
                    f"Transition '{transition.name}' is blocked by conditions (blocked: {names}).",
                    transition,
                )
            )
            continue
        passing.append(transition)

    if len(passing) > 1:
        targets = ", ".join(t.target for t in passing)
        explanation.reasons.append(
            BlockReason(
                "ambiguous",
                f"Action '{action}' resolves to multiple passing transitions "
                f"({targets}); the workflow's conditional routing is ambiguous.",
            )
        )
    elif passing:
        explanation.applicable = True
        explanation.reasons.clear()
    else:
        # No transition fully passed; the generic "no satisfying transition".
        if not explanation.reasons:
            explanation.reasons.append(
                BlockReason(
                    "no_satisfying_transition",
                    f"No transition for action '{action}' from '{state}' is both "
                    "authorized and condition-passing for this execution.",
                )
            )
    return explanation
