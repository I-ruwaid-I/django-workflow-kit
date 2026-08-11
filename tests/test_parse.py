"""Unit tests for declarative workflow parsing (parse_workflow_def)."""

import json
from pathlib import Path

import pytest
from workflow_kit import FieldEquals, parse_workflow_def
from workflow_kit.exceptions import WorkflowConfigurationError, WorkflowVersionError

VALID = {
    "name": "parse_demo",
    "initial": "draft",
    "states": ["draft", "review", "approved"],
    "transitions": [
        ("submit", "draft", "review"),
        {"name": "approve", "source": "review", "target": "approved"},
    ],
}


def test_parse_from_dict():
    workflow = parse_workflow_def(VALID)
    assert workflow.name == "parse_demo"
    assert workflow.initial == "draft"
    assert [s.name for s in workflow.states] == ["draft", "review", "approved"]
    assert workflow.actions_from("draft") == ["submit"]


def test_parse_returns_unregistered_workflow():
    from workflow_kit.engine import registry
    from workflow_kit.exceptions import WorkflowNotFoundError

    parse_workflow_def(VALID)
    with pytest.raises(WorkflowNotFoundError):
        registry.get_workflow("parse_demo")


def test_parse_from_json_string():
    workflow = parse_workflow_def(json.dumps(VALID))
    assert workflow.name == "parse_demo"


def test_parse_from_json_file(tmp_path: Path):
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(VALID), encoding="utf-8")
    workflow = parse_workflow_def(path)
    assert workflow.name == "parse_demo"


def test_name_override():
    workflow = parse_workflow_def(VALID, name="overridden")
    assert workflow.name == "overridden"


def test_states_as_labels_dict():
    definition = {
        "name": "labels",
        "initial": "a",
        "states": [{"name": "a", "label": "Alpha"}, "b"],
        "transitions": [("go", "a", "b")],
    }
    workflow = parse_workflow_def(definition)
    assert workflow.state("a").label == "Alpha"
    assert workflow.state("b").label == "B"


def test_transition_with_conditions_and_permission():
    definition = {
        "name": "c",
        "initial": "a",
        "states": ["a", "b", "c"],
        "transitions": [
            {
                "name": "approve",
                "source": "a",
                "target": "b",
                "permission": "app.approve",
                "conditions": [{"type": "field_equals", "field": "status", "value": "ok"}],
            }
        ],
    }
    workflow = parse_workflow_def(definition)
    transition = workflow.transition_for("a", "approve")
    assert transition is not None
    assert transition.permission == "app.approve"
    assert isinstance(transition.conditions[0], FieldEquals)


def test_missing_required_key_raises():
    with pytest.raises(WorkflowConfigurationError):
        parse_workflow_def({"name": "x", "initial": "a"})


def test_invalid_state_entry_raises():
    with pytest.raises(WorkflowConfigurationError):
        parse_workflow_def({**VALID, "states": [42]})


def test_invalid_transition_raises():
    with pytest.raises(WorkflowConfigurationError):
        parse_workflow_def({**VALID, "transitions": ["not-a-transition"]})


def test_invalid_string_raises():
    with pytest.raises(WorkflowConfigurationError):
        parse_workflow_def("this is not json or a file")


def test_unknown_condition_type_raises_version_error():
    definition = {
        "name": "bad",
        "initial": "a",
        "states": ["a", "b"],
        "transitions": [
            {
                "name": "go",
                "source": "a",
                "target": "b",
                "conditions": [{"type": "eval_string", "code": "1==1"}],
            }
        ],
    }
    with pytest.raises(WorkflowVersionError):
        parse_workflow_def(definition)


def test_approval_requirements_round_trip():
    definition = {
        "name": "req",
        "initial": "a",
        "states": ["a", "b"],
        "transitions": [("go", "a", "b")],
        "approval_requirements": {
            "b": {"mode": "ANY", "approvers": ["finance"], "label": "Finance check"}
        },
    }
    workflow = parse_workflow_def(definition)
    requirement = workflow.approval_requirement("b")
    assert requirement.mode == "ANY"
    assert requirement.approvers == ("finance",)
