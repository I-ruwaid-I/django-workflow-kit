"""Phase 3 tests: the derived workflow timeline.

The timeline is a structured view of the audit trail — it never stores its own
data. These tests verify that ``execution.timeline()`` returns ordered
``TimelineEvent`` records with correct labels, actors and reasons, and that the
value object is part of the public API.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from django.contrib.auth.models import Group
from workflow_kit import TimelineEvent, Transition, Workflow
from workflow_kit.engine import registry
from workflow_kit.timeline.event import timeline_label

from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


@pytest.fixture
def timeline_workflow():
    workflow = Workflow(
        name="timeline_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission=["Manager"]),
            Transition("reject", "review", "rejected", permission=["Manager"]),
        ],
    )
    yield workflow
    registry.unregister("timeline_flow")


@pytest.fixture
def invoice():
    return Invoice.objects.create(number="INV-T1", vendor="Acme", amount="100.00")


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


def test_timeline_returns_structured_events(timeline_workflow, invoice):
    execution = timeline_workflow.start(invoice)
    timeline = execution.timeline()
    assert isinstance(timeline, list)
    assert all(isinstance(item, TimelineEvent) for item in timeline)
    assert len(timeline) == 1
    assert timeline[0].event_type == "workflow_started"
    assert timeline[0].target_state == "draft"
    assert timeline[0].label == "Workflow started"


def test_timeline_tracks_full_approval_lifecycle(timeline_workflow, invoice):
    execution = timeline_workflow.start(invoice)
    submitter = _user("tim-sub")
    timeline_workflow.transition(execution, "submit", user=submitter)
    manager = _user("tim-mgr", "Manager")
    execution.approve(manager)

    labels = [e.label for e in execution.timeline()]
    assert labels == [
        "Workflow started",
        "State changed",
        "Approval required",
        "Approved",
        "State changed",
        "Workflow completed",
    ]


def test_timeline_events_carry_actors_and_reasons(timeline_workflow, invoice):
    execution = timeline_workflow.start(invoice)
    submitter = _user("tim-sub2")
    timeline_workflow.transition(execution, "submit", user=submitter)
    manager = _user("tim-mgr2", "Manager")
    execution.reject(manager, reason="missing quotation")

    timeline = execution.timeline()
    rejected = next(e for e in timeline if e.event_type == "approval_rejected")
    assert rejected.actor == "tim-mgr2"
    assert rejected.reason == "missing quotation"
    assert rejected.label == "Rejected"

    submitted = next(
        e for e in timeline if e.event_type == "transition_executed" and e.action == "submit"
    )
    assert submitted.actor == "tim-sub2"
    assert submitted.source_state == "draft"
    assert submitted.target_state == "review"


def test_timeline_orders_events_chronologically(timeline_workflow, invoice):
    execution = timeline_workflow.start(invoice)
    timeline_workflow.transition(execution, "submit")
    manager = _user("tim-mgr3", "Manager")
    execution.approve(manager)

    timeline = execution.timeline()
    timestamps = [e.timestamp for e in timeline]
    assert timestamps == sorted(timestamps)
    event_types = [e.event_type for e in timeline]
    assert event_types == [
        "workflow_started",
        "transition_executed",
        "approval_required",
        "approval_approved",
        "transition_executed",
        "workflow_completed",
    ]


def test_timeline_derives_from_audit_trail(timeline_workflow, invoice):
    execution = timeline_workflow.start(invoice)
    history_events = list(execution.history())
    timeline = execution.timeline()
    assert len(timeline) == len(history_events)
    assert [e.event_type for e in timeline] == [e.event_type for e in history_events]


def test_timeline_event_is_public_api():
    event = TimelineEvent(
        event_type="approval_approved",
        timestamp=datetime(2026, 1, 1),
    )
    assert event.label == "Approved"
    assert event.actor is None
    assert event.metadata == {}


def test_timeline_label_for_unknown_type():
    assert timeline_label("not_a_real_type") == "not_a_real_type"
    assert timeline_label("workflow_cancelled") == "Workflow cancelled"


def test_anonymous_actions_have_no_actor(timeline_workflow, invoice):
    execution = timeline_workflow.start(invoice)
    timeline_workflow.transition(execution, "submit")
    started = next(e for e in execution.timeline() if e.event_type == "workflow_started")
    assert started.actor is None
