"""Unit tests for the structured validation layer and validation reports.

These tests exercise pure-Python static analysis and never touch the database.
"""

import pytest
from workflow_kit import ValidationIssue, Workflow, validate_definition
from workflow_kit.exceptions import WorkflowValidationError


def _workflow(**overrides):
    defaults = {
        "register": False,
        "name": "validation_test",
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


def _invalid_workflow():
    """A workflow whose action 'approve' has two unconditioned transitions."""
    return Workflow(
        name="ambiguous_test",
        register=False,
        initial="draft",
        states=["draft", "a", "b"],
        transitions=[
            ("go", "draft", "a"),
            ("approve", "draft", "a"),
            ("approve", "draft", "b"),
        ],
    )


# -- ValidationReport ---------------------------------------------------------


def test_valid_workflow_has_no_errors():
    report = validate_definition(_workflow())
    assert report.is_valid is True
    assert report.errors == []
    assert report.summary() == {"errors": 0, "warnings": 0, "info": 0}


def test_ambiguous_action_is_an_error():
    report = validate_definition(_invalid_workflow())
    assert report.is_valid is False
    codes = [issue.code for issue in report.errors]
    assert "ambiguous_action" in codes


def test_unreachable_state_is_a_warning():
    workflow = _workflow(states=["draft", "review", "approved", "rejected", "orphan"])
    report = validate_definition(workflow)
    assert report.is_valid is True
    warning_codes = [issue.code for issue in report.warnings]
    assert "unreachable_state" in warning_codes


def test_self_loop_is_a_warning():
    workflow = _workflow(
        transitions=[
            ("submit", "draft", "review"),
            ("retry", "review", "review"),
            ("approve", "review", "approved"),
            ("reject", "review", "rejected"),
        ]
    )
    report = validate_definition(workflow)
    warning_codes = [issue.code for issue in report.warnings]
    assert "self_loop" in warning_codes


def test_conditional_routing_is_info_not_error():
    # True conditional routing carries conditions on each candidate.
    from workflow_kit import Transition
    from workflow_kit.conditions import FieldEquals

    workflow = Workflow(
        name="routing_test",
        register=False,
        initial="draft",
        states=["draft", "a", "b", "end"],
        transitions=[
            ("submit", "draft", "a"),
            Transition("accept", "a", "end", conditions=[FieldEquals("ok", True)]),
            Transition("accept", "a", "b", conditions=[FieldEquals("ok", False)]),
            ("reject", "b", "end"),
        ],
    )
    report = validate_definition(workflow)
    assert report.is_valid is True
    # Multiple targets for one action are flagged as info when conditions exist.
    info_codes = [issue.code for issue in report.issues if issue.severity == "info"]
    assert "conditional_routing" in info_codes


def test_report_location_is_included():
    report = validate_definition(_invalid_workflow())
    assert any(issue.location for issue in report.errors)


def test_issue_severity_classes():
    error = ValidationIssue.error("e", "msg", "loc")
    warning = ValidationIssue.warning("w", "msg", "loc")
    info = ValidationIssue.info("i", "msg", "loc")
    assert error.is_error is True
    assert warning.is_error is False
    assert info.is_error is False


def test_raise_if_invalid_payload_is_json_safe():
    report = validate_definition(_invalid_workflow())
    with pytest.raises(WorkflowValidationError) as excinfo:
        report.raise_if_invalid()
    payload = excinfo.value.payload
    assert "issues" in payload
    first = payload["issues"][0]
    assert set(first) == {"severity", "code", "message", "location"}
    assert excinfo.value.workflow == "ambiguous_test"


def test_validate_many_returns_reports_by_name():
    from workflow_kit.engine.validation import validate_many

    reports = validate_many([_workflow(), _invalid_workflow()])
    assert set(reports) == {"validation_test", "ambiguous_test"}
    assert reports["validation_test"].is_valid is True
    assert reports["ambiguous_test"].is_valid is False
