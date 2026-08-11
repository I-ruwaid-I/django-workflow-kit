"""Tests for the condition system and conditional routing.

Covers the safe evaluation of built-ins and logical conditions against a
controlled context, validates the ``Transition.conditions`` slot, and exercises
conditional execution routing through the direct transition path as well as the
approval path, with conditions re-evaluated on fresh state at decision time.
"""

from types import SimpleNamespace

import pytest
from workflow_kit import (
    All,
    Any,
    ConditionContext,
    ConditionFailedError,
    FieldEquals,
    FieldNotEquals,
    GreaterThan,
    GreaterThanOrEqual,
    IsFalse,
    IsTrue,
    LessThan,
    LessThanOrEqual,
    Not,
    Transition,
    Workflow,
    WorkflowConfigurationError,
)
from workflow_kit.conditions import conditions_met
from workflow_kit.engine import registry
from workflow_kit.exceptions import ConditionEvaluationError

from tests.test_project.demo.models import Invoice


def _context(**fields):
    return ConditionContext(
        user=None,
        workflow=None,
        execution=None,
        object=SimpleNamespace(**fields),
    )


# -- Unit: built-in conditions -----------------------------------------------


def test_field_equals_pass_and_fail():
    assert FieldEquals("amount", 100).evaluate(_context(amount=100)) is True
    assert FieldEquals("amount", 100).evaluate(_context(amount=50)) is False


def test_field_not_equals():
    assert FieldNotEquals("status", "bad").evaluate(_context(status="ok")) is True
    assert FieldNotEquals("status", "ok").evaluate(_context(status="ok")) is False


def test_comparisons():
    assert GreaterThan("amount", 100).evaluate(_context(amount=150)) is True
    assert GreaterThan("amount", 100).evaluate(_context(amount=100)) is False
    assert GreaterThanOrEqual("amount", 100).evaluate(_context(amount=100)) is True
    assert LessThan("amount", 100).evaluate(_context(amount=50)) is True
    assert LessThanOrEqual("amount", 100).evaluate(_context(amount=100)) is True
    assert LessThanOrEqual("amount", 100).evaluate(_context(amount=101)) is False


def test_boolean_conditions():
    assert IsTrue("verified").evaluate(_context(verified=True)) is True
    assert IsTrue("verified").evaluate(_context(verified=False)) is False
    assert IsFalse("verified").evaluate(_context(verified=False)) is True
    assert IsFalse("verified").evaluate(_context(verified=True)) is False


def test_dotted_path_resolution():
    context = _context(customer=SimpleNamespace(is_verified=True))
    assert IsTrue("customer.is_verified").evaluate(context) is True


def test_missing_field_raises_condition_evaluation_error():
    with pytest.raises(ConditionEvaluationError):
        FieldEquals("amount", 1).evaluate(_context(other=1))


def test_representations():
    assert repr(GreaterThan("amount", 100)) == "GreaterThan('amount' > 100)"
    assert repr(FieldEquals("amount", 100)) == "FieldEquals('amount' == 100)"
    assert repr(Not(IsTrue("verified"))) == "Not(IsTrue('verified'))"


# -- Logical operators -----------------------------------------------------


def test_all_requires_every_condition():
    rule = All(GreaterThan("amount", 100), IsTrue("verified"))
    assert rule.evaluate(_context(amount=150, verified=True)) is True
    assert rule.evaluate(_context(amount=50, verified=True)) is False
    assert rule.evaluate(_context(amount=150, verified=False)) is False


def test_any_requires_one_condition():
    rule = Any(GreaterThan("amount", 100), IsTrue("verified"))
    assert rule.evaluate(_context(amount=50, verified=True)) is True
    assert rule.evaluate(_context(amount=50, verified=False)) is False


def test_not_inverts_single_condition():
    rule = Not(LessThan("amount", 100))
    assert rule.evaluate(_context(amount=150)) is True
    assert rule.evaluate(_context(amount=50)) is False


def test_not_requires_exactly_one_condition():
    with pytest.raises(WorkflowConfigurationError):
        Not().evaluate(_context(amount=1))
    with pytest.raises(WorkflowConfigurationError):
        Not(IsTrue("x"), IsTrue("y")).evaluate(_context(x=True, y=True))


def test_composite_accepts_single_condition_list():
    rule = All([GreaterThan("amount", 100)])
    assert rule.evaluate(_context(amount=150)) is True
    assert rule.evaluate(_context(amount=50)) is False


def test_composite_rejects_non_condition():
    with pytest.raises(WorkflowConfigurationError):
        All("not-a-condition")


# -- Transition.conditions ---------------------------------------------------


def test_transition_rejects_non_condition():
    with pytest.raises(WorkflowConfigurationError):
        Transition("approve", "review", "approved", conditions=["nope"])


def test_transition_accepts_single_and_list():
    single = Transition("a", "x", "y", conditions=GreaterThan("amount", 1))
    assert len(single.conditions) == 1
    multi = Transition("b", "x", "y", conditions=[GreaterThan("amount", 1), IsTrue("ok")])
    assert len(multi.conditions) == 2
    assert Transition("c", "x", "y").conditions == ()


def test_conditions_met_is_and_semantics():
    transition = Transition(
        "approve",
        "review",
        "approved",
        conditions=[GreaterThan("amount", 1), FieldEquals("currency", "USD")],
    )
    passing = _context(amount=150, currency="USD")
    failing = _context(amount=150, currency="EUR")
    assert conditions_met(transition, passing) is True
    assert conditions_met(transition, failing) is False


# -- DB-backed conditional routing ------------------------------------------


@pytest.fixture
def workflow():
    # Two branches share the "approve" action; amounts above 1000 but at or
    # below 5000 match no branch and are therefore blocked (a routing gap).
    workflow = Workflow(
        name="condition_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected", "big_approved"],
        transitions=[
            ("submit", "draft", "review"),
            Transition(
                "approve",
                "review",
                "approved",
                conditions=[LessThanOrEqual("amount", 1_000)],
            ),
            Transition(
                "approve",
                "review",
                "big_approved",
                conditions=[GreaterThan("amount", 5_000)],
            ),
            ("reject", "review", "rejected"),
        ],
    )
    yield workflow
    registry.unregister("condition_flow")


@pytest.fixture
def invoice():
    return Invoice.objects.create(number="INV-COND", vendor="Acme", amount="500.00")


@pytest.mark.django_db
def test_conditions_gate_available_actions(workflow, invoice, user):
    execution = workflow.start(invoice)
    execution.transition("submit", user=user)
    assert execution.available_actions(user=user) == ["approve", "reject"]
    assert execution.can_transition("approve", user=user) is True


@pytest.mark.django_db
def test_conditional_routing_selects_target(workflow, invoice, user):
    execution = workflow.start(invoice)
    execution.transition("submit", user=user)
    execution.transition("approve", user=user)
    assert execution.current_state == "approved"

    big = workflow.start(Invoice.objects.create(number="INV-BIG", vendor="Acme", amount="6000.00"))
    big.transition("submit", user=user)
    big.transition("approve", user=user)
    assert big.current_state == "big_approved"


@pytest.mark.django_db
def test_approval_path_routes_conditionally(workflow, invoice, user):
    execution = workflow.start(invoice)
    execution.transition("submit", user=user)
    execution.approve(user=user)
    assert execution.current_state == "approved"

    big = workflow.start(Invoice.objects.create(number="INV-BIG2", vendor="Acme", amount="6000.00"))
    big.transition("submit", user=user)
    big.approve(user=user)
    assert big.current_state == "big_approved"


@pytest.mark.django_db
def test_routing_gap_hides_action_and_raises(workflow, user):
    """An amount that matches no branch is neither available nor runnable."""
    invoice = Invoice.objects.create(number="INV-GAP", vendor="Acme", amount="2000.00")
    execution = workflow.start(invoice)
    execution.transition("submit", user=user)

    assert execution.can_transition("approve", user=user) is False
    assert execution.available_actions(user=user) == ["reject"]
    with pytest.raises(ConditionFailedError):
        execution.transition("approve", user=user)


@pytest.mark.django_db
def test_overlapping_conditions_raise_configuration_error(user):
    """Two passing branches for one action are ambiguous and rejected."""
    from workflow_kit.engine import registry

    ambiguous = Workflow(
        name="ambiguous_flow",
        initial="draft",
        states=["draft", "review", "approved", "big_approved"],
        transitions=[
            ("submit", "draft", "review"),
            Transition(
                "approve",
                "review",
                "approved",
                conditions=[LessThanOrEqual("amount", 1_000)],
            ),
            Transition(
                "approve",
                "review",
                "big_approved",
                conditions=[GreaterThanOrEqual("amount", 500)],
            ),
        ],
    )
    try:
        invoice = Invoice.objects.create(number="INV-AMB", vendor="Acme", amount="700.00")
        execution = ambiguous.start(invoice)
        execution.transition("submit", user=user)
        # The ambiguous action is hidden because it cannot be resolved.
        assert execution.available_actions(user=user) == []
        with pytest.raises(WorkflowConfigurationError):
            execution.transition("approve", user=user)
    finally:
        registry.unregister("ambiguous_flow")
