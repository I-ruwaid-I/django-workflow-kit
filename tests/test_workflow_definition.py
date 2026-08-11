"""Unit tests for workflow definitions, validation and the registry.

These tests exercise pure-Python behaviour and never touch the database.
"""

import pytest
from workflow_kit import (
    State,
    Transition,
    Workflow,
    WorkflowConfigurationError,
    WorkflowNotFoundError,
    get_workflow,
)
from workflow_kit.engine import registry


def _workflow(**overrides):
    defaults = {
        "register": False,
        "name": "definition_test",
        "initial": "draft",
        "states": ["draft", "review", "approved", "rejected"],
        "transitions": [
            ("submit", "draft", "review"),
            ("approve", "review", "approved"),
            ("reject", "review", "rejected"),
        ],
    }
    defaults.update(overrides)
    return Workflow(**defaults)


# -- State and Transition construction --------------------------------------


def test_state_label_defaults_to_prettified_name():
    assert State("manager_review").label == "Manager Review"


def test_state_custom_label():
    assert State("draft", label="New").label == "New"


def test_state_empty_name_raises():
    with pytest.raises(WorkflowConfigurationError):
        State("")


def test_transition_label_defaults_to_prettified_name():
    assert Transition("submit", "draft", "review").label == "Submit"


def test_transition_empty_name_raises():
    with pytest.raises(WorkflowConfigurationError):
        Transition("", "draft", "review")


# -- Worker creation and validation ------------------------------------------


def test_workflow_construction_and_introspection():
    workflow = _workflow()
    assert workflow.initial == "draft"
    assert [state.name for state in workflow.states] == [
        "draft",
        "review",
        "approved",
        "rejected",
    ]
    assert workflow.state("approved").label == "Approved"


def test_empty_name_raises():
    with pytest.raises(WorkflowConfigurationError):
        _workflow(name="")


def test_empty_states_raises():
    with pytest.raises(WorkflowConfigurationError):
        _workflow(states=[])


def test_duplicate_state_raises():
    with pytest.raises(WorkflowConfigurationError):
        _workflow(states=["draft", "draft", "review"])


def test_initial_state_must_exist():
    with pytest.raises(WorkflowConfigurationError):
        _workflow(initial="missing")


def test_unknown_source_state_raises():
    with pytest.raises(WorkflowConfigurationError):
        _workflow(transitions=[("submit", "unknown_state", "review")])


def test_unknown_target_state_raises():
    with pytest.raises(WorkflowConfigurationError):
        _workflow(transitions=[("submit", "draft", "unknown_state")])


def test_identical_transition_duplicate_raises():
    # Same action, same source, same target is a pointless duplicate.
    with pytest.raises(WorkflowConfigurationError):
        _workflow(
            transitions=[
                ("submit", "draft", "review"),
                ("submit", "draft", "review"),
            ]
        )


def test_same_action_to_different_targets_allowed_for_conditions():
    # Same action, different targets from one source is allowed; conditions
    # route the execution at runtime (conditional routing).
    from workflow_kit.conditions import FieldEquals

    workflow = _workflow(
        transitions=[
            ("submit", "draft", "review"),
            Transition(
                "approve",
                "review",
                "approved",
                conditions=[FieldEquals("status", "ok")],
            ),
            Transition(
                "approve",
                "review",
                "rejected",
                conditions=[FieldEquals("status", "bad")],
            ),
        ]
    )
    assert [t.target for t in workflow.transitions_for_action("review", "approve")] == [
        "approved",
        "rejected",
    ]


def test_transition_objects_accepted():
    workflow = _workflow(
        transitions=[
            Transition("submit", "draft", "review"),
            Transition("approve", "review", "approved"),
        ]
    )
    assert workflow.actions_from("draft") == ["submit"]
    assert workflow.actions_from("review") == ["approve"]


# -- Introspection -----------------------------------------------------------


def test_actions_from_in_definition_order():
    workflow = _workflow(
        transitions=[
            ("reject", "draft", "rejected"),
            ("submit", "draft", "review"),
        ]
    )
    assert workflow.actions_from("draft") == ["reject", "submit"]


def test_actions_from_unknown_state_is_empty():
    assert _workflow().actions_from("missing") == []


def test_transition_for_returns_matching_transition():
    transition = _workflow().transition_for("draft", "submit")
    assert transition is not None
    assert transition.target == "review"


def test_transition_for_missing_returns_none():
    assert _workflow().transition_for("draft", "nope") is None


def test_terminal_states_are_derived():
    workflow = _workflow()
    assert workflow.terminal_states == frozenset({"approved", "rejected"})
    assert workflow.is_terminal("approved") is True
    assert workflow.is_terminal("review") is False


def test_state_lookup_unknown_raises():
    with pytest.raises(WorkflowNotFoundError):
        _workflow().state("missing")


def test_state_equality():
    assert State("draft") == State("draft")
    assert State("draft") == "draft"


# -- Registry ----------------------------------------------------------------


def test_registration_and_lookup():
    workflow = Workflow(
        name="registry-demo",
        initial="a",
        states=["a", "b"],
        transitions=[("go", "a", "b")],
    )
    assert get_workflow("registry-demo") is workflow


def test_duplicate_registration_raises():
    with pytest.raises(WorkflowConfigurationError):
        Workflow(
            name="registry-demo",
            initial="a",
            states=["a", "b"],
            transitions=[("go", "a", "b")],
        )


def test_skip_registration():
    workflow = _workflow(register=True)
    workflow2 = _workflow(name="not-registered", register=False)
    with pytest.raises(WorkflowNotFoundError):
        get_workflow("not-registered")
    assert workflow2 != workflow


def test_get_workflow_unknown_raises():
    with pytest.raises(WorkflowNotFoundError):
        get_workflow("no-such-workflow")


def test_all_workflows_includes_registered():
    names = {workflow.name for workflow in registry.all_workflows()}
    assert "registry-demo" in names
