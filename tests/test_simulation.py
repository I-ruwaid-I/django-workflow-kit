"""Unit tests for the dry-run simulation engine."""

import pytest
from workflow_kit import (
    NoPathFoundError,
    Workflow,
    simulate,
    simulate_all,
)
from workflow_kit.engine.simulation import SimStep


def _workflow(**overrides):
    defaults = {
        "register": False,
        "name": "simulation_test",
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


# -- simulate -----------------------------------------------------------------


def test_simulate_full_path():
    workflow = _workflow()
    result = simulate(workflow, ["submit", "approve"])
    assert result.completed is True
    assert result.terminal == "approved"
    assert result.states == ["draft", "review", "approved"]
    assert [step.action for step in result.steps] == ["submit", "approve"]


def test_simulate_steps_are_named():
    workflow = _workflow()
    result = simulate(workflow, ["submit"])
    assert result.steps == [SimStep("submit", "draft", "review")]
    assert str(result.steps[0]) == "submit: draft -> review"


def test_simulate_blocks_on_invalid_action():
    workflow = _workflow()
    result = simulate(workflow, ["submit", "submit"])
    assert result.completed is False
    assert result.blocked == "submit"
    assert result.terminal == "review"


def test_simulate_unknown_action_blocks():
    workflow = _workflow()
    result = simulate(workflow, ["nope"])
    assert result.blocked == "nope"


def test_simulate_custom_start():
    workflow = _workflow()
    result = simulate(workflow, ["approve"], start="review")
    assert result.terminal == "approved"
    assert result.states[0] == "review"


def test_simulate_with_gate():
    workflow = _workflow()

    def gate(transition):
        return transition.name != "approve"

    result = simulate(workflow, ["submit", "approve"], gate=gate)
    assert result.blocked == "approve"


def test_simulate_max_steps():
    workflow = _workflow()
    result = simulate(workflow, ["submit", "approve"], max_steps=0)
    assert result.blocked == "submit"


# -- simulate_all -------------------------------------------------------------


def test_simulate_all_enumerates_every_path():
    workflow = _workflow()
    results = simulate_all(workflow)
    ends = sorted(r.terminal for r in results)
    assert ends == ["approved", "rejected"]
    assert all(r.completed for r in results)


def test_simulate_all_custom_start():
    workflow = _workflow()
    results = simulate_all(workflow, start="draft")
    assert len(results) == 2


# -- verify_always_completes --------------------------------------------------


def test_verify_completes_passes_for_wellformed():
    from workflow_kit.engine.simulation import verify_always_completes

    verify_always_completes(_workflow())  # must not raise


def test_verify_completes_raises_on_dead_end():
    from workflow_kit.engine.simulation import verify_always_completes

    workflow = Workflow(
        name="dead",
        register=False,
        initial="a",
        states=["a", "b"],
        transitions=[("go", "a", "b")],  # 'b' is a terminal state with no exit
    )
    verify_always_completes(workflow)  # reaching a terminal is fine

    # A real dead-end: a state that loops and can never reach a terminal.
    workflow = Workflow(
        name="trapped",
        register=False,
        initial="a",
        states=["a", "b"],
        transitions=[("go", "a", "b"), ("back", "b", "b")],
    )
    with pytest.raises(NoPathFoundError):
        verify_always_completes(workflow)


def test_verify_completes_raises_on_closed_cycle():
    from workflow_kit.engine.simulation import verify_always_completes

    workflow = Workflow(
        name="cycle",
        register=False,
        initial="a",
        states=["a", "b"],
        transitions=[("go", "a", "b"), ("back", "b", "a")],
    )
    with pytest.raises(NoPathFoundError):
        verify_always_completes(workflow)
