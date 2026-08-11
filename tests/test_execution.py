"""Database-backed tests for workflow executions and transitions."""

from unittest.mock import patch

import pytest
from django.db import IntegrityError
from workflow_kit import (
    InvalidTransitionError,
    Workflow,
    WorkflowAlreadyCompletedError,
    WorkflowNotFoundError,
)
from workflow_kit.engine import registry
from workflow_kit.models import WorkflowExecution

from tests.test_project.demo.models import Invoice


@pytest.fixture
def workflow():
    workflow = Workflow(
        name="execution_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "review"),
            ("approve", "review", "approved"),
            ("reject", "review", "rejected"),
        ],
    )
    yield workflow
    registry.unregister("execution_flow")


@pytest.fixture
def invoice():
    return Invoice.objects.create(number="INV-E1", vendor="Acme", amount="100.00")


@pytest.mark.django_db
def test_start_creates_execution_in_initial_state(workflow, invoice):
    execution = workflow.start(invoice)
    assert execution.pk is not None
    assert execution.current_state == "draft"
    assert execution.is_completed is False
    assert execution.object == invoice


@pytest.mark.django_db
def test_get_execution_round_trip(workflow, invoice):
    workflow.start(invoice)
    execution = workflow.get_execution(invoice)
    assert execution.current_state == "draft"
    assert execution.workflow_name == "execution_flow"


@pytest.mark.django_db
def test_get_execution_missing_raises(workflow, invoice):
    with pytest.raises(WorkflowNotFoundError):
        workflow.get_execution(invoice)


@pytest.mark.django_db
def test_transition_moves_state(workflow, invoice):
    execution = workflow.start(invoice)
    workflow.transition(execution, "submit")
    assert execution.current_state == "review"
    assert execution.pk is not None


@pytest.mark.django_db
def test_transition_to_terminal_state_sets_completed(workflow, invoice):
    execution = workflow.start(invoice)
    workflow.transition(execution, "submit")
    workflow.transition(execution, "approve")
    assert execution.current_state == "approved"
    assert execution.is_completed is True
    assert execution.completed_at is not None


@pytest.mark.django_db
def test_invalid_transition_raises_and_leaves_state(workflow, invoice):
    execution = workflow.start(invoice)
    with pytest.raises(InvalidTransitionError):
        workflow.transition(execution, "approve")
    assert execution.current_state == "draft"


@pytest.mark.django_db
def test_completed_workflow_cannot_transition(workflow, invoice):
    execution = workflow.start(invoice)
    workflow.transition(execution, "submit")
    workflow.transition(execution, "approve")
    with pytest.raises(WorkflowAlreadyCompletedError):
        workflow.transition(execution, "submit")
    assert execution.current_state == "approved"


@pytest.mark.django_db
def test_multiple_executions_are_independent(workflow, invoice):
    first = workflow.start(invoice)
    second_invoice = Invoice.objects.create(number="INV-E2", vendor="Globex", amount="200.00")
    second = workflow.start(second_invoice)
    workflow.transition(first, "submit")
    assert first.current_state == "review"
    assert second.current_state == "draft"


@pytest.mark.django_db
def test_double_start_raises_integrity_error(workflow, invoice):
    workflow.start(invoice)
    with pytest.raises(IntegrityError):
        workflow.start(invoice)


@pytest.mark.django_db
def test_available_actions_progression(workflow, invoice):
    execution = workflow.start(invoice)
    assert workflow.available_actions(execution) == ["submit"]
    workflow.transition(execution, "submit")
    assert set(workflow.available_actions(execution)) == {"approve", "reject"}
    workflow.transition(execution, "approve")
    assert workflow.available_actions(execution) == []


@pytest.mark.django_db
def test_can_transition_and_current_state(workflow, invoice):
    execution = workflow.start(invoice)
    assert workflow.current_state(execution) == "draft"
    assert workflow.can_transition(execution, "submit") is True
    assert workflow.can_transition(execution, "approve") is False
    workflow.transition(execution, "submit")
    assert workflow.can_transition(execution, "approve") is True


@pytest.mark.django_db
def test_execution_convenience_methods(workflow, invoice):
    execution = workflow.start(invoice)
    assert execution.state_label == "Draft"
    assert execution.available_actions() == ["submit"]
    assert execution.can_transition("submit") is True
    execution.transition("submit")
    assert execution.current_state == "review"
    assert execution.workflow is workflow


@pytest.mark.django_db(transaction=True)
def test_transition_is_atomic_on_failure(workflow, invoice):
    execution = workflow.start(invoice)
    with (
        patch(
            "workflow_kit.models.execution.WorkflowExecution.save",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(RuntimeError),
    ):
        workflow.transition(execution, "submit")
    fresh = WorkflowExecution.objects.get(pk=execution.pk)
    assert fresh.current_state == "draft"
