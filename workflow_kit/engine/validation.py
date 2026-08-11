"""Workflow definition validation and validation reports.

Phase 11 adds a structured validation layer on top of the eager construction
rules already enforced by :class:`~workflow_kit.engine.workflow.Workflow`.
Construction catches configuration errors (unknown states, duplicate
transitions, invalid permission specs, ...); this module adds *static
analysis* over a fully built definition:

- reachability: every state reachable from the initial state?
- ambiguous routing: an action that will always resolve to more than one
  rule when all its conditions pass simultaneously;
- dead transitions: transitions that can never be taken;
- notification of approval requirements on non-terminal states.

Validation never touches the database and never runs user code (conditions are
inspected by class/name only, not evaluated).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from workflow_kit.exceptions import WorkflowValidationError

if TYPE_CHECKING:
    from workflow_kit.engine.workflow import Workflow

from workflow_kit.engine.introspection import reachable_states

_SEVERITY_ERROR = "error"
_SEVERITY_WARNING = "warning"
_SEVERITY_INFO = "info"


@dataclass(frozen=True)
class ValidationIssue:
    """A single finding from a validation pass.

    ``severity`` is ``"error"`` (invalid definition), ``"warning"``
    (questionable but valid) or ``"info"`` (informational note). ``code`` is a
    stable machine-readable identifier and ``location`` points at the offending
    part (e.g. ``transitions[2]`` or ``states[3]``).
    """

    severity: str
    code: str
    message: str
    location: str = ""

    @classmethod
    def error(cls, code: str, message: str, location: str = "") -> ValidationIssue:
        return cls(_SEVERITY_ERROR, code, message, location)

    @classmethod
    def warning(cls, code: str, message: str, location: str = "") -> ValidationIssue:
        return cls(_SEVERITY_WARNING, code, message, location)

    @classmethod
    def info(cls, code: str, message: str, location: str = "") -> ValidationIssue:
        return cls(_SEVERITY_INFO, code, message, location)

    @property
    def is_error(self) -> bool:
        return self.severity == _SEVERITY_ERROR


@dataclass
class ValidationReport:
    """The result of validating one workflow definition.

    ``issues`` keeps findings in discovery order. ``is_valid`` is True only
    when there are no errors.
    """

    workflow_name: str
    issues: list[ValidationIssue] = field(default_factory=list)

    def add(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.is_error]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == _SEVERITY_WARNING]

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def summary(self) -> dict[str, int]:
        """Count findings by severity (``errors`` / ``warnings`` / ``info``)."""
        return {
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "info": sum(1 for issue in self.issues if issue.severity == _SEVERITY_INFO),
        }

    def raise_if_invalid(self) -> ValidationReport:
        """Raise :class:`WorkflowValidationError` when the definition is invalid.

        The exception payload carries the full issue list as JSON-safe dicts.
        """
        if self.errors:
            raise WorkflowValidationError(
                f"Workflow '{self.workflow_name}' is invalid: {len(self.errors)} error(s).",
                workflow=self.workflow_name,
                payload={
                    "issues": [
                        {
                            "severity": issue.severity,
                            "code": issue.code,
                            "message": issue.message,
                            "location": issue.location,
                        }
                        for issue in self.issues
                    ]
                },
            )
        return self


def _build_outgoing(workflow: Workflow) -> dict[str, list[Any]]:
    """Map every state to its transitions in definition order."""
    outgoing: dict[str, list[Any]] = {}
    for state in workflow.states:
        outgoing[state.name] = workflow.transitions_from(state.name)
    return outgoing


def validate_definition(workflow: Workflow) -> ValidationReport:
    """Run static analysis over ``workflow`` and return a report.

    The report is always returned (even for invalid definitions); call
    :meth:`ValidationReport.raise_if_invalid` to raise a
    :class:`~workflow_kit.exceptions.WorkflowValidationError` carrying the
    finding payload.
    """
    report = ValidationReport(workflow_name=workflow.name)
    outgoing = _build_outgoing(workflow)
    reachable = reachable_states(workflow)

    for state in workflow.states:
        transitions = outgoing.get(state.name, [])

        if state.name not in reachable:
            report.add(
                ValidationIssue.warning(
                    "unreachable_state",
                    f"State '{state.name}' can never be reached from the initial "
                    f"state '{workflow.initial}'.",
                    f"states[{workflow.states.index(state)}]",
                )
            )

        grouped: dict[str, list[Any]] = {}
        for transition in transitions:
            grouped.setdefault(transition.name, []).append(transition)

        for action, candidates in grouped.items():
            for index, transition in enumerate(candidates):
                location = f"transitions[{transition.source}->{transition.target}:{action}]"
                if len(candidates) > 1 and not any(c.conditions for c in candidates):
                    report.add(
                        ValidationIssue.error(
                            "ambiguous_action",
                            f"Action '{action}' from state '{state.name}' has "
                            f"{len(candidates)} transitions but no conditions to "
                            "disambiguate them; the action can never resolve "
                            "safely.",
                            location,
                        )
                    )

                if transition.source == transition.target and not transition.conditions:
                    report.add(
                        ValidationIssue.warning(
                            "self_loop",
                            f"Transition '{action}' from '{transition.source}' to "
                            "'{transition.target}' is an unconditional self-loop; "
                            "executions entering it will loop forever.",
                            location,
                        )
                    )
                if index == 0 and len(candidates) > 1:
                    report.add(
                        ValidationIssue.info(
                            "conditional_routing",
                            f"Action '{action}' from '{state.name}' uses "
                            "conditional routing to resolve its target.",
                            location,
                        )
                    )

    # Approval requirements only make sense on non-terminal states.
    for state in workflow.states:
        requirement = workflow.approval_requirement(state.name)
        if workflow.is_terminal(state.name) and requirement.approvers:
            report.add(
                ValidationIssue.info(
                    "approval_on_terminal",
                    f"State '{state.name}' is terminal yet declares an approval "
                    "requirement; approvals will never be satisfied.",
                    f"states[{workflow.states.index(state)}]",
                )
            )

    return report


def validate_many(workflows: list[Workflow]) -> dict[str, ValidationReport]:
    """Validate several definitions and return reports keyed by workflow name."""
    return {workflow.name: validate_definition(workflow) for workflow in workflows}
