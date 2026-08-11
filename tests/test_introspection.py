"""Unit tests for workflow introspection, reachability and path enumeration."""

import json

from workflow_kit import Workflow, reachable_states, workflow_to_dict
from workflow_kit.engine.introspection import path_states, simple_paths


def _workflow(**overrides):
    defaults = {
        "register": False,
        "name": "introspect_test",
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


# -- workflow_to_dict ---------------------------------------------------------


def test_dump_is_json_safe():
    dumped = workflow_to_dict(_workflow())
    json.dumps(dumped)  # must not raise
    assert dumped["name"] == "introspect_test"
    assert dumped["initial"] == "draft"
    assert dumped["metrics"]["state_count"] == 4
    assert dumped["metrics"]["transition_count"] == 3
    assert dumped["metrics"]["terminal_count"] == 2


def test_dump_flags_initial_terminal_reachable():
    dumped = workflow_to_dict(_workflow())
    by_name = {state["name"]: state for state in dumped["states"]}
    assert by_name["draft"]["initial"] is True
    assert by_name["draft"]["terminal"] is False
    assert by_name["approved"]["terminal"] is True
    assert by_name["approved"]["reachable"] is True


def test_dump_reports_unreachable_state():
    workflow = _workflow(states=["draft", "review", "approved", "rejected", "orphan"])
    dumped = workflow_to_dict(workflow)
    by_name = {state["name"]: state for state in dumped["states"]}
    assert by_name["orphan"]["reachable"] is False
    assert dumped["metrics"]["unreachable_state_count"] == 1


# -- reachability -------------------------------------------------------------


def test_reachable_states_from_initial():
    workflow = _workflow()
    assert reachable_states(workflow) == {
        "draft",
        "review",
        "approved",
        "rejected",
    }


def test_reachable_states_ignores_orphan():
    workflow = _workflow(states=["draft", "review", "approved", "rejected", "orphan"])
    assert "orphan" not in reachable_states(workflow)


def test_reachable_states_from_custom_start():
    workflow = _workflow()
    assert reachable_states(workflow, start="review") == {"review", "approved", "rejected"}


# -- simple paths -------------------------------------------------------------


def test_simple_paths_reach_every_terminal():
    workflow = _workflow()
    paths = simple_paths(workflow)
    assert len(paths) == 2
    path_targets = {p[-1].target for p in paths}
    assert path_targets == {"approved", "rejected"}


def test_simple_paths_to_specific_end():
    workflow = _workflow()
    paths = simple_paths(workflow, end="rejected")
    assert len(paths) == 1
    assert [t.name for t in paths[0]] == ["submit", "reject"]


def test_path_states_helper():
    workflow = _workflow()
    path = simple_paths(workflow, end="approved")[0]
    assert path_states(path, "draft") == ["draft", "review", "approved"]


def test_simple_paths_terminal_start_returns_single_empty_path():
    workflow = _workflow()
    paths = simple_paths(workflow, start="approved")
    assert paths == [[]]


def test_max_length_bounds_paths():
    workflow = Workflow(
        name="long",
        register=False,
        initial="a",
        states=["a", "b", "end"],
        transitions=[
            ("one", "a", "b"),
            ("one", "b", "end"),
        ],
    )
    assert simple_paths(workflow, max_length=0) == []
    assert len(simple_paths(workflow, max_length=2)) == 1
    assert simple_paths(workflow, max_length=1) == []
