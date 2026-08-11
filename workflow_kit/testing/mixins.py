"""Assertion helpers for workflow behaviour in tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from workflow_kit.engine.validation import ValidationReport, validate_definition
from workflow_kit.engine.workflow import Workflow


class WorkflowValidationMixin:
    """Mixin that validates workflow definitions inside tests.

    :meth:`assert_valid_workflow` returns the workflow so it can be used
    inline (``wf = self.assert_valid_workflow(...)``) and raises
    :class:`AssertionError` with the full validation report when the definition
    has errors.
    """

    @staticmethod
    def validation_report(workflow: Workflow) -> ValidationReport:
        """Run static validation and return the report."""
        return validate_definition(workflow)

    def assert_valid_workflow(self, workflow: Workflow) -> Workflow:
        """Assert ``workflow`` passes static validation; returns it."""
        report = self.validation_report(workflow)
        if not report.is_valid:
            messages = "\n".join(f"  - {issue.message}" for issue in report.errors)
            raise AssertionError(f"Workflow '{workflow.name}' failed validation:\n{messages}")
        return workflow

    def assert_invalid_workflow(
        self,
        workflow: Workflow,
        *,
        code: str | None = None,
    ) -> ValidationReport:
        """Assert ``workflow`` fails validation, optionally by issue ``code``."""
        report = self.validation_report(workflow)
        assert not report.is_valid, f"Workflow '{workflow.name}' unexpectedly passed validation."
        if code is not None:
            assert any(issue.code == code for issue in report.errors), (
                f"Expected a '{code}' validation error, got: {[i.code for i in report.errors]}."
            )
        return report


class ExecutionAssertions:
    """Assertions around a live workflow execution's observable state.

    Useful in integration tests that drive executions through real transitions.
    """

    @staticmethod
    def assert_state(execution: Any, state: str) -> Any:
        """Assert ``execution`` is in ``state``; returns ``execution``."""
        assert execution.current_state == state, (
            f"Expected state '{state}', got '{execution.current_state}'."
        )
        return execution

    @staticmethod
    def assert_available_actions(
        execution: Any,
        actions: Sequence[str],
        *,
        user: Any = None,
    ) -> Any:
        """Assert ``execution.available_actions(user)`` equals the given set."""
        actual = execution.available_actions(user=user)
        assert sorted(actual) == sorted(actions), (
            f"Expected available actions {sorted(actions)}, got {sorted(actual)}."
        )
        return execution

    @staticmethod
    def assert_can_transition(execution: Any, action: str, *, user: Any = None) -> Any:
        """Assert ``action`` can transition ``execution`` for ``user``."""
        assert execution.can_transition(action, user=user), (
            f"Expected action '{action}' to be allowed, but it is not."
        )
        return execution

    @staticmethod
    def assert_cannot_transition(execution: Any, action: str, *, user: Any = None) -> Any:
        """Assert ``action`` cannot transition ``execution`` for ``user``."""
        assert not execution.can_transition(action, user=user), (
            f"Expected action '{action}' to be blocked, but it is allowed."
        )
        return execution


def assert_valid(workflow: Workflow) -> Workflow:
    """Standalone equivalent of :meth:`WorkflowValidationMixin.assert_valid_workflow`.

    Convenient in plain unit functions without a mixin.
    """
    report = validate_definition(workflow)
    if not report.is_valid:
        messages = "\n".join(f"  - {issue.message}" for issue in report.errors)
        raise AssertionError(f"Workflow '{workflow.name}' failed validation:\n{messages}")
    return workflow
