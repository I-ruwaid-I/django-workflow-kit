"""Phase 10 tests: the attachment subsystem.

Attachments let participants attach files to an execution. These tests verify
the convenience method on the execution model, the service layer (storage via
Django's default storage, audit + domain event emission), the REST endpoint for
multipart uploads, and that time-vs-name metadata is captured.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient
from workflow_kit import Transition, Workflow
from workflow_kit.events.types import EventType
from workflow_kit.models import (
    WorkflowAttachment,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowExecution,
)

from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


@pytest.fixture
def attachment_workflow():
    workflow = Workflow(
        name="attachment_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission=["Manager"]),
        ],
    )
    yield workflow
    from workflow_kit.engine import registry

    registry.unregister("attachment_flow")


@pytest.fixture
def invoice():
    return Invoice.objects.create(number="INV-AT1", vendor="Acme", amount="100.00")


@pytest.fixture
def execution(attachment_workflow, invoice) -> WorkflowExecution:
    return attachment_workflow.start(invoice)


@pytest.fixture
def manager():
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="attach_mgr")


def _upload(name: str = "receipt.pdf", content: bytes = b"%PDF-1.4 fake", **kwargs):
    return SimpleUploadedFile(name, content, **kwargs)


# -- execution convenience method ---------------------------------------------


def test_upload_stores_file_and_metadata(execution, manager):
    upload = _upload()
    attachment = execution.add_attachment(upload=upload, user=manager)
    assert isinstance(attachment, WorkflowAttachment)
    assert attachment.execution_id == execution.pk
    assert attachment.uploaded_by == manager
    assert attachment.name == "receipt.pdf"
    assert attachment.size == len(b"%PDF-1.4 fake")
    assert attachment.extension == "pdf"
    assert attachment.file.name  # exercised lazily: file was stored
    assert upload.name == "receipt.pdf"


def test_upload_with_explicit_name(execution, manager):
    attachment = execution.add_attachment(upload=_upload(), name="proof.pdf", user=manager)
    assert attachment.name == "proof.pdf"


def test_upload_records_audit_and_domain_events(execution, manager):
    captured: list[EventType] = []
    from workflow_kit import subscribe

    unsubscribe = subscribe(EventType.ATTACHMENT_ADDED, lambda e: captured.append(e.type))
    try:
        execution.add_attachment(upload=_upload(), user=manager)
    finally:
        unsubscribe()

    event = WorkflowEvent.objects.get(
        execution=execution, event_type=WorkflowEventType.ATTACHMENT_ADDED
    )
    assert event.user == manager
    assert event.metadata["name"] == "receipt.pdf"
    assert EventType.ATTACHMENT_ADDED in captured


def test_attachment_appears_in_timeline(execution, manager):
    execution.add_attachment(upload=_upload(), user=manager)
    timeline = execution.timeline()
    entry = next(e for e in timeline if e.event_type == "attachment_added")
    assert entry.label == "Attachment added"
    assert entry.actor == "attach_mgr"


def test_attachment_listing_is_ordered(execution, manager):
    execution.add_attachment(upload=_upload("a.txt"), user=manager)
    execution.add_attachment(upload=_upload("b.txt"), user=manager)
    names = [a.name for a in WorkflowAttachment.objects.filter(execution=execution)]
    assert names == ["a.txt", "b.txt"]


def test_extension_property(execution, manager):
    attachment = execution.add_attachment(upload=_upload("SCAN.JPG"), user=manager)
    assert attachment.extension == "jpg"


def test_attachment_slug_helper():
    from workflow_kit.attachments import attachment_slug

    assert attachment_slug("Final Quote.pdf") == "final-quote.pdf"
    assert attachment_slug("scan copy.JPG") == "scan-copy.JPG"
    assert attachment_slug("!!.txt") == "attachment.txt"


# -- REST API -----------------------------------------------------------------


def _client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_api_lists_attachments(execution, manager):
    execution.add_attachment(upload=_upload(), user=manager)
    client = _client_for(manager)
    response = client.get(f"/api/executions/{execution.pk}/attachments/")
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) == 1
    assert response.data[0]["name"] == "receipt.pdf"
    assert response.data[0]["extension"] == "pdf"
    assert response.data[0]["size"] == len(b"%PDF-1.4 fake")


def test_api_uploads_attachment(execution, manager):
    client = _client_for(manager)
    response = client.post(
        f"/api/executions/{execution.pk}/attachments/",
        {"file": _upload("quote.pdf", b"quote")},
        format="multipart",
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["name"] == "quote.pdf"
    assert WorkflowAttachment.objects.filter(execution=execution).count() == 1


def test_api_upload_requires_file(execution, manager):
    client = _client_for(manager)
    response = client.post(
        f"/api/executions/{execution.pk}/attachments/",
        {},
        format="multipart",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_api_requires_authentication_for_attachments(execution):
    client = APIClient()
    response = client.get(f"/api/executions/{execution.pk}/attachments/")
    assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
