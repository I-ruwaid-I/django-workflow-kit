"""Phase 10 tests: the comment subsystem.

Comments attach free-form discussion to an execution. These tests verify the
convenience method on the execution model, the service layer (audit event +
domain event emission), actor recording for named and anonymous users, ordering,
the REST endpoints and that comments surface in the derived timeline.
"""

from __future__ import annotations

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from workflow_kit import Transition, Workflow
from workflow_kit.events.types import EventType
from workflow_kit.models import WorkflowComment, WorkflowEvent, WorkflowEventType, WorkflowExecution

from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


@pytest.fixture
def comment_workflow():
    workflow = Workflow(
        name="comment_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission=["Manager"]),
        ],
    )
    yield workflow
    from workflow_kit.engine import registry

    registry.unregister("comment_flow")


@pytest.fixture
def invoice():
    return Invoice.objects.create(number="INV-C1", vendor="Acme", amount="100.00")


@pytest.fixture
def execution(comment_workflow, invoice) -> WorkflowExecution:
    return comment_workflow.start(invoice)


@pytest.fixture
def manager():
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="comment_mgr")


# -- execution convenience method ---------------------------------------------


def test_add_comment_records_user_text_and_timestamp(execution, manager):
    comment = execution.add_comment(user=manager, text="Please attach the quotation.")
    assert isinstance(comment, WorkflowComment)
    assert comment.execution_id == execution.pk
    assert comment.user == manager
    assert comment.text == "Please attach the quotation."
    assert comment.created_at is not None
    assert timezone.is_aware(comment.created_at)


def test_comment_trimmed_but_blank_allowed(execution, manager):
    comment = execution.add_comment(user=manager, text="  hello  ")
    assert comment.text == "hello"


def test_comment_listing_is_ordered(execution, manager):
    execution.add_comment(user=manager, text="first")
    execution.add_comment(user=manager, text="second")
    comments = list(WorkflowComment.objects.filter(execution=execution))
    assert [c.text for c in comments] == ["first", "second"]


def test_anonymous_comment_records_no_user(execution):
    comment = execution.add_comment(user=None, text="system note")
    assert comment.user is None
    assert comment.author_label == "anonymous"


def test_comment_is_scoped_to_its_execution(comment_workflow, invoice):
    other_invoice = Invoice.objects.create(number="INV-C2", vendor="Globex", amount="50.00")
    execution = comment_workflow.start(invoice)
    other = comment_workflow.start(other_invoice)
    comment = execution.add_comment(user=None, text="note")
    assert comment.execution_id == execution.pk
    assert list(other.comments.all()) == []
    assert list(execution.comments.all()) == [comment]
    assert WorkflowComment.objects.filter(execution=other).count() == 0
    assert WorkflowComment.objects.filter(execution=execution).count() == 1


# -- audit + domain events ----------------------------------------------------


def test_add_comment_writes_audit_event(execution, manager):
    execution.add_comment(user=manager, text="audit me")
    event = WorkflowEvent.objects.get(
        execution=execution, event_type=WorkflowEventType.COMMENT_ADDED
    )
    assert event.user == manager
    assert event.action == "comment"
    assert "comment_id" in event.metadata


def test_add_comment_emits_domain_event(execution, manager):
    captured: list[EventType] = []

    def handler(event):
        captured.append(event.type)

    from workflow_kit import subscribe

    unsubscribe = subscribe(EventType.COMMENT_ADDED, handler)
    try:
        execution.add_comment(user=manager, text="event me")
    finally:
        unsubscribe()
    assert EventType.COMMENT_ADDED in captured


def test_comment_appears_in_timeline(execution, manager):
    execution.add_comment(user=manager, text="timeline note")
    timeline = execution.timeline()
    assert any(entry.event_type == "comment_added" for entry in timeline)
    entry = next(e for e in timeline if e.event_type == "comment_added")
    assert entry.label == "Comment added"
    assert entry.actor == "comment_mgr"


# -- REST API -----------------------------------------------------------------


def _client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_api_lists_comments(execution, manager):
    execution.add_comment(user=manager, text="from the api")
    client = _client_for(manager)
    response = client.get(f"/api/executions/{execution.pk}/comments/")
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) == 1
    assert response.data[0]["text"] == "from the api"
    assert response.data[0]["author"] == "comment_mgr"


def test_api_adds_comment(execution, manager):
    client = _client_for(manager)
    response = client.post(
        f"/api/executions/{execution.pk}/comments/",
        {"text": "posted through drf"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["text"] == "posted through drf"
    assert response.data["author"] == "comment_mgr"
    assert WorkflowComment.objects.filter(execution=execution).count() == 1


def test_api_rejects_blank_comment(execution, manager):
    client = _client_for(manager)
    response = client.post(
        f"/api/executions/{execution.pk}/comments/",
        {"text": ""},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_api_requires_authentication_for_comments(execution):
    client = APIClient()
    response = client.get(f"/api/executions/{execution.pk}/comments/")
    assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
