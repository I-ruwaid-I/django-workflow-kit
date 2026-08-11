"""Phase 3 tests: the append-only audit trail.

Verifies that every workflow action records a structured, ordered event and
that the audit trail is immutable through the public API.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser, Group
from workflow_kit import AuditError, Transition, Workflow
from workflow_kit.audit.service import event_history, latest_event, record_event
from workflow_kit.engine import registry
from workflow_kit.models import WorkflowEvent, WorkflowEventType

from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


@pytest.fixture
def audit_workflow():
    workflow = Workflow(
        name="audit_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission=["Manager"]),
            Transition("reject", "review", "rejected", permission=["Manager"]),
        ],
    )
    yield workflow
    registry.unregister("audit_flow")


@pytest.fixture
def invoice():
    return Invoice.objects.create(number="INV-AU1", vendor="Acme", amount="100.00")


def _user(username: str, *groups: str):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={"password": "test-password-123"},
    )
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


# -- recording -----------------------------------------------------------------


def test_start_records_workflow_started_event(audit_workflow, invoice):
    execution = audit_workflow.start(invoice)
    events = list(event_history(execution))
    assert len(events) == 1
    event = events[0]
    assert event.event_type == WorkflowEventType.WORKFLOW_STARTED
    assert event.target_state == "draft"
    assert event.created_at is not None


def test_transition_and_completion_events_are_recorded(audit_workflow, invoice):
    execution = audit_workflow.start(invoice)
    audit_workflow.transition(execution, "submit", user=_user("sub"))
    manager = _user("mgray", "Manager")
    audit_workflow.transition(execution, "approve", user=manager)

    types = [e.event_type for e in event_history(execution)]
    assert types == [
        WorkflowEventType.WORKFLOW_STARTED,
        WorkflowEventType.TRANSITION_EXECUTED,
        WorkflowEventType.APPROVAL_REQUIRED,
        WorkflowEventType.TRANSITION_EXECUTED,
        WorkflowEventType.WORKFLOW_COMPLETED,
    ]


def test_approval_decisions_record_events(audit_workflow, invoice):
    execution = audit_workflow.start(invoice)
    audit_workflow.transition(execution, "submit")
    manager = _user("mgr-aud", "Manager")

    execution.reject(manager, reason="bad")
    rejected = [
        e for e in event_history(execution) if e.event_type == WorkflowEventType.APPROVAL_REJECTED
    ]
    assert len(rejected) == 1
    assert rejected[0].reason == "bad"
    assert rejected[0].action == "reject"
    assert rejected[0].user == manager


def test_events_carry_source_target_and_actor(audit_workflow, invoice):
    execution = audit_workflow.start(invoice)
    submitter = _user("sub-2")
    audit_workflow.transition(execution, "submit", user=submitter)
    manager = _user("mgr-b", "Manager")
    audit_workflow.transition(execution, "approve", user=manager)

    events = list(execution.history())
    submit_event = next(e for e in events if e.action == "submit")
    approve_event = next(
        e
        for e in events
        if e.event_type == WorkflowEventType.TRANSITION_EXECUTED and e.action == "approve"
    )
    assert submit_event.source_state == "draft"
    assert submit_event.target_state == "review"
    assert approve_event.user == manager
    assert approve_event.metadata == {}


def test_anonymous_actors_are_recorded_without_user(audit_workflow, invoice):
    execution = audit_workflow.start(invoice)
    audit_workflow.transition(execution, "submit", user=AnonymousUser())
    event = latest_event(execution)
    assert event.action == "submit"
    assert event.user is None


def test_record_event_allows_custom_metadata_and_reason(invoice):
    execution = _bare_execution(invoice)
    event = record_event(
        execution,
        event_type=WorkflowEventType.APPROVAL_APPROVED,
        action="signed",
        source_state="draft",
        target_state="approved",
        reason="looks fine",
        metadata={"approval": 42},
    )
    assert event.reason == "looks fine"
    assert event.metadata == {"approval": 42}
    assert event.created_at is not None


# -- ordering & latest --------------------------------------------------------


def test_history_ordered_by_timestamp_then_id(audit_workflow, invoice):
    execution = audit_workflow.start(invoice)
    audit_workflow.transition(execution, "submit")
    events = list(execution.history())
    timestamps = [e.created_at for e in events]
    assert timestamps == sorted(timestamps)


def test_latest_event_returns_last(invoice):
    execution = _bare_execution(invoice)
    record_event(execution, event_type=WorkflowEventType.WORKFLOW_STARTED, action="start")
    record_event(execution, event_type=WorkflowEventType.TRANSITION_EXECUTED, action="submit")
    assert latest_event(execution).action == "submit"


# -- immutability -------------------------------------------------------------


def test_events_are_appendonly_no_updates(invoice):
    execution = _bare_execution(invoice)
    event = record_event(execution, event_type=WorkflowEventType.WORKFLOW_STARTED, action="start")
    event.action = "changed"
    with pytest.raises(AuditError):
        event.save()


def test_event_model_rejects_save_after_create(invoice):
    execution = _bare_execution(invoice)
    event = WorkflowEvent.objects.create(
        execution=execution,
        event_type=str(WorkflowEventType.WORKFLOW_STARTED),
    )
    with pytest.raises(AuditError):
        event.save()


def _bare_execution(invoice):
    from workflow_kit.models import WorkflowExecution

    return WorkflowExecution.objects.create(
        workflow_name="_bare_",
        object=invoice,
        current_state="draft",
    )
