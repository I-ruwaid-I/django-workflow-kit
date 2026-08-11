"""Phase 5 tests: the domain event system.

Verifies the event vocabulary, payload structure, deterministic dispatching and
the transaction-aware behavior that keeps event delivery out of the workflow
transaction while never corrupting workflow state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from workflow_kit import (
    DomainEvent,
    EventType,
    InvalidTransitionError,
    ObjectRef,
    Transition,
    Workflow,
)
from workflow_kit.engine import registry
from workflow_kit.events import (
    ALL_EVENTS,
    EventDispatcher,
    default_dispatcher,
    dispatch,
    emit,
    subscribe,
)
from workflow_kit.events.emitter import capture, flush

from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


def _event(**overrides) -> DomainEvent:
    fields = dict(
        type=EventType.WORKFLOW_TRANSITIONED,
        workflow="evt_flow",
        execution_id=1,
        object=ObjectRef(app_label="tests", model_name="invoice", pk=1, display="INV-X"),
        actor="alice",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        source_state="draft",
        target_state="review",
        action="submit",
    )
    fields.update(overrides)
    return DomainEvent(**fields)


# -- event vocabulary & payload -------------------------------------------------


def test_event_type_enum_values():
    assert EventType.WORKFLOW_STARTED == "workflow.started"
    assert EventType.WORKFLOW_TRANSITIONED == "workflow.transitioned"
    assert EventType.WORKFLOW_COMPLETED == "workflow.completed"
    assert EventType.WORKFLOW_CANCELLED == "workflow.cancelled"
    assert EventType.WORKFLOW_REJECTED == "workflow.rejected"
    assert EventType.APPROVAL_CREATED == "approval.created"
    assert EventType.APPROVAL_APPROVED == "approval.approved"
    assert EventType.APPROVAL_REJECTED == "approval.rejected"


def test_event_payload_exposes_structured_fields():
    event = _event(execution_id=7, action="approve", target_state="approved")
    assert event.type == EventType.WORKFLOW_TRANSITIONED
    assert event.workflow == "evt_flow"
    assert event.execution_id == 7
    assert event.object.app_label == "tests"
    assert event.object.model_name == "invoice"
    assert event.object.pk == 1
    assert event.object.display == "INV-X"
    assert event.actor == "alice"
    assert event.source_state == "draft"
    assert event.target_state == "approved"
    assert event.action == "approve"
    assert event.metadata == {}


def test_object_ref_scope_and_dict():
    ref = _event().object
    assert ref.scope() == "tests.invoice"
    assert ref.to_dict() == {"type": "tests.invoice", "id": 1, "display": "INV-X"}


def test_event_metadata_round_trips_custom_data():
    event = _event(metadata={"approval": 42})
    assert event.metadata == {"approval": 42}


def test_event_immutable_and_has_unique_id():
    first = _event()
    second = _event()
    assert first != second
    assert first.id != second.id
    with pytest.raises(AttributeError):
        first.type = EventType.WORKFLOW_COMPLETED


# -- dispatching ----------------------------------------------------------------


def test_subscribe_and_unsubscribe():
    dispatcher = EventDispatcher()
    seen = []
    unsub = dispatcher.subscribe(EventType.WORKFLOW_STARTED, seen.append)
    dispatcher.dispatch(_event(type=EventType.WORKFLOW_STARTED))
    assert len(seen) == 1
    unsub()
    dispatcher.dispatch(_event(type=EventType.WORKFLOW_STARTED))
    assert len(seen) == 1


def test_subscribe_accepts_string_and_wildcard():
    dispatcher = EventDispatcher()
    seen = []
    unsub_a = dispatcher.subscribe("workflow.transitioned", seen.append)
    unsub_b = dispatcher.subscribe(ALL_EVENTS, seen.append)
    dispatcher.dispatch(_event())
    dispatcher.dispatch(_event(type=EventType.APPROVAL_APPROVED))
    assert len(seen) == 3
    unsub_a()
    unsub_b()


def test_dispatch_order_is_deterministic():
    dispatcher = EventDispatcher()
    order = []
    unsubs = [
        dispatcher.subscribe(EventType.WORKFLOW_STARTED, lambda e, i=i: order.append(i))
        for i in range(5)
    ]
    dispatcher.dispatch(_event(type=EventType.WORKFLOW_STARTED))
    assert order == [0, 1, 2, 3, 4]
    for unsub in unsubs:
        unsub()


def test_handler_failure_is_isolated():
    dispatcher = EventDispatcher()
    calls = []

    def _boom(_event):
        calls.append("boom")
        raise RuntimeError("handler failure")

    def _after(_event):
        calls.append("after")

    dispatcher.subscribe(EventType.WORKFLOW_STARTED, _boom)
    dispatcher.subscribe(EventType.WORKFLOW_STARTED, _after)
    dispatcher.dispatch(_event(type=EventType.WORKFLOW_STARTED))
    assert calls == ["boom", "after"]


def test_non_callable_handler_rejected():
    dispatcher = EventDispatcher()
    with pytest.raises(TypeError):
        dispatcher.subscribe(EventType.WORKFLOW_STARTED, "not-a-callable")  # type: ignore[arg-type]


def test_default_dispatcher_aliases_work():
    seen = []
    unsub = subscribe(ALL_EVENTS, seen.append)
    try:
        dispatch(_event(type=EventType.WORKFLOW_STARTED))
    finally:
        unsub()
    assert len(seen) == 1


def test_dispatcher_clear_removes_all():
    dispatcher = EventDispatcher()
    seen = []
    dispatcher.subscribe(ALL_EVENTS, seen.append)
    dispatcher.clear()
    dispatcher.dispatch(_event(type=EventType.WORKFLOW_STARTED))
    assert seen == []


# -- capture / emit transaction semantics ----------------------------------------


def test_emit_outside_capture_dispatches_immediately():
    seen = []
    unsub = subscribe(ALL_EVENTS, seen.append)
    try:
        emit(_event(type=EventType.WORKFLOW_STARTED))
    finally:
        unsub()
    assert len(seen) == 1


def test_capture_dispatches_events_on_success_in_order():
    seen = []
    unsub = subscribe(ALL_EVENTS, seen.append)
    try:
        with capture():
            emit(_event(type=EventType.WORKFLOW_STARTED))
            emit(_event(type=EventType.WORKFLOW_TRANSITIONED))
    finally:
        unsub()
    assert [str(e.type) for e in seen] == ["workflow.started", "workflow.transitioned"]


def test_capture_discards_events_on_failure():
    seen = []
    unsub = subscribe(ALL_EVENTS, seen.append)
    try:
        with pytest.raises(RuntimeError), capture():
            emit(_event(type=EventType.WORKFLOW_STARTED))
            raise RuntimeError("transition failed")
    finally:
        unsub()
    assert seen == []


def test_flush_dispatches_collection_in_order():
    seen = []
    unsub = subscribe(ALL_EVENTS, seen.append)
    try:
        events = [
            _event(type=EventType.WORKFLOW_STARTED),
            _event(type=EventType.WORKFLOW_TRANSITIONED),
        ]
        n = flush(events)
    finally:
        unsub()
    assert n == 2
    assert [str(e.type) for e in seen] == ["workflow.started", "workflow.transitioned"]


# -- engine integration ----------------------------------------------------------


@pytest.fixture
def evt_workflow():
    workflow = Workflow(
        name="evt_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission=["Manager"]),
            Transition("reject", "review", "rejected", permission=["Manager"]),
        ],
    )
    yield workflow
    registry.unregister("evt_flow")


@pytest.fixture
def invoice():
    return Invoice.objects.create(number="INV-EV1", vendor="Acme", amount="100.00")


def _subscribe_all():
    handlers = []
    unsubscribe = subscribe(ALL_EVENTS, handlers.append)
    return handlers, unsubscribe


def test_start_emits_workflow_started(evt_workflow, invoice):
    handlers, unsubscribe = _subscribe_all()
    try:
        execution = evt_workflow.start(invoice)
    finally:
        unsubscribe()
    assert [str(e.type) for e in handlers] == ["workflow.started"]
    started = handlers[0]
    assert started.execution_id == execution.pk
    assert started.object.display == "INV-EV1"
    assert started.target_state == "draft"
    assert started.actor is None


def test_transition_emits_expected_event_sequence(evt_workflow, invoice):
    handlers, unsubscribe = _subscribe_all()
    try:
        execution = evt_workflow.start(invoice)
        evt_workflow.transition(execution, "submit")
    finally:
        unsubscribe()
    types = [str(e.type) for e in handlers]
    assert types == ["workflow.started", "workflow.transitioned", "approval.created"]


def test_terminal_transition_emits_completion_event(evt_workflow, invoice):
    manager = _manager("mgr-term")
    handlers, unsubscribe = _subscribe_all()
    try:
        execution = evt_workflow.start(invoice)
        evt_workflow.transition(execution, "submit", user=manager)
        evt_workflow.transition(execution, "approve", user=manager)
    finally:
        unsubscribe()
    types = [str(e.type) for e in handlers]
    assert "workflow.completed" in types
    completed = next(e for e in handlers if e.type == EventType.WORKFLOW_COMPLETED)
    assert completed.source_state == "review"
    assert completed.target_state == "approved"


def test_reject_emits_workflow_rejected(evt_workflow, invoice):
    manager = _manager("mgr-rej")
    handlers, unsubscribe = _subscribe_all()
    try:
        execution = evt_workflow.start(invoice)
        evt_workflow.transition(execution, "submit", user=manager)
        evt_workflow.transition(execution, "reject", user=manager)
    finally:
        unsubscribe()
    types = [str(e.type) for e in handlers]
    assert EventType.WORKFLOW_REJECTED in types
    reject_event = next(e for e in handlers if e.type == EventType.WORKFLOW_REJECTED)
    assert reject_event.target_state == "rejected"


def _manager(username: str):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group

    user, _ = get_user_model().objects.get_or_create(
        username=username,
        defaults={"password": "test-password-123"},
    )
    group, _ = Group.objects.get_or_create(name="Manager")
    user.groups.add(group)
    user.save()
    return user


def test_event_actor_from_transitioning_user(evt_workflow, invoice, user_factory):
    manager = _manager("mgr")
    submitter = user_factory("submit")
    handlers, unsubscribe = _subscribe_all()
    try:
        execution = evt_workflow.start(invoice)
        evt_workflow.transition(execution, "submit", user=submitter)
        evt_workflow.transition(execution, "approve", user=manager)
    finally:
        unsubscribe()
    approve_event = next(e for e in handlers if e.type == EventType.WORKFLOW_COMPLETED)
    assert approve_event.actor == "mgr"
    submit_event = next(
        e for e in handlers if e.type == EventType.WORKFLOW_TRANSITIONED and e.action == "submit"
    )
    assert submit_event.actor == "submit"


def test_failed_transition_does_not_emit_events(evt_workflow, invoice):
    handlers, unsubscribe = _subscribe_all()
    try:
        execution = evt_workflow.start(invoice)
        with pytest.raises(InvalidTransitionError):
            evt_workflow.transition(execution, "approve")  # wrong source state
    finally:
        unsubscribe()
    types = [str(e.type) for e in handlers]
    assert "workflow.transitioned" not in types


@pytest.mark.django_db(transaction=True)
def test_rolled_back_transaction_discards_events(evt_workflow, invoice):
    """A rolled-back transition must not deliver its events."""
    handlers = []
    unsubscribe = default_dispatcher.subscribe(ALL_EVENTS, handlers.append)
    try:
        execution = evt_workflow.start(invoice)
        with (
            patch(
                "workflow_kit.models.execution.WorkflowExecution.save",
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(RuntimeError),
        ):
            evt_workflow.transition(execution, "submit")
    finally:
        unsubscribe()
    # The start events were delivered; the failed transition's events were not.
    types = [str(e.type) for e in handlers]
    assert types == ["workflow.started"]


def test_approval_decision_emits_approval_events(evt_workflow, invoice):
    manager = _manager("mgr-evt")
    handlers, unsubscribe = _subscribe_all()
    try:
        execution = evt_workflow.start(invoice)
        evt_workflow.transition(execution, "submit", user=manager)
        execution.approve(user=manager, reason="ok")
    finally:
        unsubscribe()
    types = [str(e.type) for e in handlers]
    assert EventType.APPROVAL_APPROVED in types
    assert EventType.WORKFLOW_COMPLETED in types
    approval_event = next(e for e in handlers if e.type == EventType.APPROVAL_APPROVED)
    assert approval_event.metadata.get("approval") is not None
    assert approval_event.actor == "mgr-evt"
