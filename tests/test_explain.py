"""Unit tests for explain / why-not diagnostics.

The explainers are read-only and pure Python; they are exercised here with a
stub execution and a minimal condition context rather than the ORM.
"""

from workflow_kit import Transition, Workflow, explain, why_not


def PermissionTransition(name: str, source: str, target: str) -> Transition:
    return Transition(name, source, target, permission="app.approve")


class _FieldBag:
    """A tiny object exposing declared attribute values."""

    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _Context:
    def __init__(self, **fields) -> None:
        self.object = _FieldBag(**fields)


class _StubExecution:
    """Minimal execution stand-in exposing exactly what explainers need."""

    def __init__(self, state: str) -> None:
        self.current_state = state
        self.state = state


def _workflow(**overrides):
    from workflow_kit import Transition
    from workflow_kit.conditions import GreaterThan

    defaults = {
        "register": False,
        "name": "explain_test",
        "initial": "draft",
        "states": ["draft", "review", "approved", "rejected"],
        "transitions": [
            ("submit", "draft", "review"),
            ("approve", "review", "approved"),
            ("reject", "review", "rejected"),
            Transition(
                "auto",
                "draft",
                "approved",
                conditions=[GreaterThan("amount", 1000)],
            ),
        ],
    }
    defaults.update(overrides)
    return Workflow(**defaults)


# -- explain: structural ------------------------------------------------------


def test_explain_applicable_action():
    workflow = _workflow()
    execution = _StubExecution("review")
    explanation = explain(workflow, execution, "approve")
    assert explanation.applicable is True
    assert explanation.reasons == []


def test_explain_unknown_action():
    workflow = _workflow()
    execution = _StubExecution("review")
    explanation = explain(workflow, execution, "nope")
    assert explanation.applicable is False
    kinds = {reason.kind for reason in explanation.reasons}
    assert "no_action" in kinds


def test_explain_terminal_state_blocks_everything():
    workflow = _workflow()
    execution = _StubExecution("approved")
    explanation = explain(workflow, execution, "approve")
    assert explanation.applicable is False
    kinds = {reason.kind for reason in explanation.reasons}
    assert "terminal" in kinds


# -- explain: conditions ------------------------------------------------------


def test_explain_condition_failure_lists_blocked_condition():
    workflow = _workflow()
    execution = _StubExecution("draft")
    context = _Context(amount=10)  # does NOT satisfy amount > 1000
    explanation = explain(workflow, execution, "auto", condition_context=context)
    assert explanation.applicable is False
    kinds = {reason.kind for reason in explanation.reasons}
    assert "condition" in kinds
    assert any("GreaterThan" in reason.detail for reason in explanation.reasons)


def test_explain_condition_pass_allows_auto():
    workflow = _workflow()
    execution = _StubExecution("draft")
    context = _Context(amount=999999)
    explanation = explain(workflow, execution, "auto", condition_context=context)
    assert explanation.applicable is True


# -- explain: permissions -----------------------------------------------------


def test_explain_permission_denied():
    workflow = Workflow(
        name="perm_test",
        register=False,
        initial="draft",
        states=["draft", "approved"],
        transitions=[PermissionTransition("approve", "draft", "approved")],
    )
    execution = _StubExecution("draft")

    class NoPermUser:
        is_authenticated = True

        def has_perm(self, perm) -> bool:
            return False

    explanation = explain(workflow, execution, "approve", user=NoPermUser())
    assert explanation.applicable is False
    kinds = {reason.kind for reason in explanation.reasons}
    assert "permission" in kinds


def test_explain_permission_granted():
    workflow = Workflow(
        name="perm_test",
        register=False,
        initial="draft",
        states=["draft", "approved"],
        transitions=[PermissionTransition("approve", "draft", "approved")],
    )
    execution = _StubExecution("draft")

    class HasPermUser:
        is_authenticated = True

        def has_perm(self, perm) -> bool:
            return True

    explanation = explain(workflow, execution, "approve", user=HasPermUser())
    assert explanation.applicable is True


def test_explain_anonymous_user_denied_protected_transition():
    workflow = Workflow(
        name="perm_test",
        register=False,
        initial="draft",
        states=["draft", "approved"],
        transitions=[PermissionTransition("approve", "draft", "approved")],
    )
    execution = _StubExecution("draft")
    explanation = explain(workflow, execution, "approve", user=None)
    assert explanation.applicable is False
    kinds = {reason.kind for reason in explanation.reasons}
    assert "permission" in kinds


# -- why_not ------------------------------------------------------------------


def test_why_not_is_explain_for_blocked():
    workflow = _workflow()
    execution = _StubExecution("review")
    explanation = why_not(workflow, execution, "submit")
    assert explanation.applicable is False
    kinds = {reason.kind for reason in explanation.reasons}
    assert "no_action" in kinds


def test_why_not_applicable_action_gives_value_error():
    # why_not is a diagnostic for blocked actions; an applicable action simply
    # is reported applicable with no reasons.
    workflow = _workflow()
    execution = _StubExecution("review")
    explanation = why_not(workflow, execution, "approve")
    assert explanation.applicable is True
