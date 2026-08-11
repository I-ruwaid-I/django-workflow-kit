"""Unit tests for the testing utilities package."""

import pytest
from workflow_kit import Workflow
from workflow_kit.testing import (
    ExecutionAssertions,
    SimpleWorkflow,
    WorkflowValidationMixin,
    workflow_factory,
)


class _StubExecution:
    def __init__(self, state: str, actions: list[str] | None = None) -> None:
        self.current_state = state
        self._actions = actions or []

    def available_actions(self, user=None):
        return list(self._actions)

    def can_transition(self, action, user=None):
        return action in self._actions


# -- mixins -------------------------------------------------------------------


class _Suite(WorkflowValidationMixin):
    pass


def test_assert_valid_workflow_passes():
    suite = _Suite()
    workflow = suite.assert_valid_workflow(workflow_factory("valid_mixin", register=False))
    assert workflow.name == "valid_mixin"


def test_assert_invalid_workflow_catches_ambiguous():
    suite = _Suite()
    workflow = Workflow(
        name="bad_mixin",
        register=False,
        initial="a",
        states=["a", "b", "c"],
        transitions=[("go", "a", "b"), ("go", "a", "c")],  # ambiguous
    )
    report = suite.assert_invalid_workflow(workflow, code="ambiguous_action")
    assert report.is_valid is False


def test_assert_valid_workflow_raises_on_bad():
    suite = _Suite()
    workflow = Workflow(
        name="worse_mixin",
        register=False,
        initial="a",
        states=["a", "b", "c"],
        transitions=[("go", "a", "b"), ("go", "a", "c")],
    )
    with pytest.raises(AssertionError, match="failed validation"):
        suite.assert_valid_workflow(workflow)


# -- ExecutionAssertions ------------------------------------------------------


def test_execution_assertions_state():
    assertions = ExecutionAssertions()
    execution = _StubExecution("review")
    assert assertions.assert_state(execution, "review") is execution
    with pytest.raises(AssertionError):
        assertions.assert_state(execution, "draft")


def test_execution_assertions_actions():
    assertions = ExecutionAssertions()
    execution = _StubExecution("review", ["approve", "reject"])
    assertions.assert_available_actions(execution, ["reject", "approve"])
    with pytest.raises(AssertionError):
        assertions.assert_available_actions(execution, ["approve"])


def test_execution_assertions_transition():
    assertions = ExecutionAssertions()
    execution = _StubExecution("review", ["approve"])
    assertions.assert_can_transition(execution, "approve")
    assertions.assert_cannot_transition(execution, "reject")


# -- factories ----------------------------------------------------------------


def test_workflow_factory_defaults():
    workflow = workflow_factory("factory_defaults", register=False)
    assert [s.name for s in workflow.states] == [
        "draft",
        "review",
        "approved",
        "rejected",
    ]
    assert workflow.actions_from("draft") == ["submit"]
    assert workflow.actions_from("review") == ["approve", "reject"]


def test_workflow_factory_overrides():
    workflow = workflow_factory(
        "factory_override",
        register=False,
        initial="a",
        states=["a", "b"],
        transitions=[("go", "a", "b")],
    )
    assert workflow.initial == "a"
    assert workflow.actions_from("a") == ["go"]


def test_workflow_factory_registers_by_default():
    from workflow_kit.engine import registry

    workflow = workflow_factory("factory_registered")
    try:
        assert registry.get_workflow("factory_registered") is workflow
    finally:
        registry.unregister("factory_registered")


def test_simple_workflow():
    simple = SimpleWorkflow("simple_demo", register=False)
    assert simple.workflow.initial == "a"
    assert simple.workflow.is_terminal("c") is True


def test_workflow_module_helper():
    from workflow_kit.testing.factories import workflow_module

    workflows = workflow_module()
    assert workflows[0].name == "cli_demo"


def test_unregister_all_clears_registered_workflows():
    from workflow_kit.engine import registry
    from workflow_kit.exceptions import WorkflowNotFoundError
    from workflow_kit.testing.factories import unregister_all

    workflow = workflow_factory("to_clean")
    assert registry.get_workflow("to_clean") is workflow
    unregister_all()
    with pytest.raises(WorkflowNotFoundError):
        registry.get_workflow("to_clean")
