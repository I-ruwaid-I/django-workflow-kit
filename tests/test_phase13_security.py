"""Phase 13 tests: security audit (PHASE13 ``#17``-``#23``).

Attempts unauthorized operations directly against the REST API, admin and
engine (not just the UI), and verifies the package's security posture:

- the REST API requires authentication and never exposes engine internals;
- authorization is enforced by the engine, not by the HTTP layer;
- analytics stay gated behind staff / ``view_analytics``;
- admin is read-only for inspection only;
- attachments enforce a size/content-type policy and never leak predictable
  storage URLs unless explicitly enabled;
- webhook payloads and structured logs carry no secrets.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from rest_framework import status
from rest_framework.test import APIClient
from workflow_kit import AttachmentError, Transition, Workflow
from workflow_kit.engine import registry

from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


def _user(username: str, *groups: str, **kwargs: Any) -> Any:
    from django.contrib.auth.models import Group

    user, _ = get_user_model().objects.get_or_create(
        username=username, defaults={"password": "pw", **kwargs}
    )
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


def _client_for(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def sec_workflow():
    workflow = Workflow(
        name="sec_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            Transition("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission=["Manager"]),
            Transition("reject", "review", "rejected", permission=["Manager"]),
        ],
    )
    yield workflow
    registry.unregister("sec_flow")


@pytest.fixture
def invoice():
    return Invoice.objects.create(number="SEC-1", vendor="Acme", amount="100.00")


@pytest.fixture
def execution(sec_workflow, invoice):
    return sec_workflow.start(invoice)


# -- #17/#18: authorization boundary across HTTP methods -----------------------


def test_unauthenticated_methods_are_denied(execution):
    """Every execution endpoint refuses anonymous access, across all methods."""
    client = APIClient()
    paths = [
        "/api/executions/",
        f"/api/executions/{execution.pk}/",
        f"/api/executions/{execution.pk}/transition/",
        f"/api/executions/{execution.pk}/comments/",
        f"/api/executions/{execution.pk}/attachments/",
    ]
    for method in ("get", "post", "put", "patch", "delete"):
        for path in paths:
            response = getattr(client, method)(path)
            assert response.status_code in (
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ), f"{method.upper()} {path}"


def test_write_methods_are_not_exposed(sec_workflow, execution):
    """Executions are read/act-only; PUT/PATCH/DELETE must not exist."""
    mgr = _user("sec_mgr", "Manager")
    client = _client_for(mgr)
    for method in ("put", "patch", "delete"):
        response = getattr(client, method)(f"/api/executions/{execution.pk}/", {})
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED, method.upper()


def test_unauthorized_user_cannot_transition_via_api(sec_workflow, execution):
    """A user without the role cannot approve through the API, ever."""

    clerk = _user("sec_clerk", "Clerk")
    sec_workflow.transition(execution, "submit", user=_user("sec_emp", "Employee"))

    response = _client_for(clerk).post(
        f"/api/executions/{execution.pk}/transition/", {"action": "approve"}, format="json"
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["error"] == "permission_denied"
    execution.refresh_from_db()
    assert execution.current_state == "review"


def test_anonymous_cannot_comment_or_upload(execution):
    client = APIClient()
    assert client.post(
        f"/api/executions/{execution.pk}/comments/", {"text": "hi"}, format="json"
    ).status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
    assert client.post(
        f"/api/executions/{execution.pk}/attachments/",
        {"file": SimpleUploadedFile("x.pdf", b"x")},
        format="multipart",
    ).status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


def test_error_responses_do_not_leak_internal_details(sec_workflow, execution):
    """Engine errors map to stable codes; no tracebacks reach the client."""
    sec_workflow.transition(execution, "submit", user=_user("sec_emp2", "Employee"))
    response = _client_for(_user("sec_clerk2", "Clerk")).post(
        f"/api/executions/{execution.pk}/transition/", {"action": "approve"}, format="json"
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    body = response.json()
    assert set(body) == {"error", "message"}
    assert "Traceback" not in str(body)
    assert 'File "' not in str(body)


# -- #19/#20: isolation and sensitive data -------------------------------------


def test_webhook_payload_contains_no_secrets():
    """Webhook bodies expose public event fields, never credentials."""
    from django.utils import timezone
    from workflow_kit.events.types import ObjectRef
    from workflow_kit.notifications.webhook import WebhookProvider

    class _Event:
        id = "evt-1"
        type = "workflow.completed"
        workflow = "sec_flow"
        workflow_version = 1
        execution_id = 7
        object = ObjectRef("demo", "invoice", 7)
        actor = "someone"
        timestamp = timezone.now()
        source_state = "review"
        target_state = "approved"
        action = "approve"
        metadata = {}

    payload = WebhookProvider().payload(_Event())
    text = str(payload)
    for secret in ("password", "token", "secret", "api_key", "WEBHOOK_SECRET"):
        assert secret not in text.lower()


def test_structured_log_payload_has_no_payload_fields():
    """Structured event logs carry event metadata, not business payloads."""
    import logging

    from django.utils import timezone
    from workflow_kit.events.types import ObjectRef
    from workflow_kit.observability import StructuredEventLogger

    class _Event:
        id = "evt-2"
        type = "workflow.started"
        workflow = "sec_flow"
        workflow_version = 1
        execution_id = 8
        object = ObjectRef("demo", "invoice", 8)
        actor = "someone"
        timestamp = timezone.now()
        source_state = "draft"
        target_state = "review"
        action = "submit"
        metadata = {"text": "TOP-SECRET-NOTE"}

    records: list[logging.LogRecord] = []

    class _Sink(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("workflow_kit_sec_test")
    logger.setLevel(logging.INFO)
    sink = _Sink()
    logger.addHandler(sink)
    try:
        StructuredEventLogger(log=logger).handle(_Event())
    finally:
        logger.handlers.clear()

    assert len(records) == 1
    payload = records[0].workflow_event
    assert payload["event"] == "workflow.started"
    assert "TOP-SECRET-NOTE" not in str(payload)
    assert "text" not in payload


# -- #21: attachment security --------------------------------------------------


def test_attachment_name_is_sanitized_for_path_traversal(execution):
    """Traversal and absolute paths in upload names cannot escape storage."""
    from workflow_kit.attachments import attachment_slug

    assert attachment_slug("../../etc/passwd") == "passwd"
    assert attachment_slug("..\\..\\windows\\boot.ini") == "boot.ini"
    assert attachment_slug("/etc/shadow.pdf") == "shadow.pdf"
    assert "/" not in attachment_slug("a/b/c.txt")
    assert "\\" not in attachment_slug("a\\b\\c.txt")


def test_attachment_size_policy_is_enforced(execution, settings):
    """Uploads over the configured cap are refused before storage."""
    from workflow_kit.attachments.service import add_attachment

    settings.WORKFLOW_KIT = {
        **settings.WORKFLOW_KIT,
        "ATTACHMENT_MAX_SIZE": 4,
    }
    with pytest.raises(AttachmentError):
        add_attachment(
            execution,
            upload=SimpleUploadedFile("big.pdf", b"0123456789"),
            user=_user("sec_emp3", "Employee"),
        )


def test_attachment_content_type_policy_is_enforced(execution, settings):
    """Uploads with disallowed content types are refused before storage."""
    from workflow_kit.attachments.service import add_attachment

    settings.WORKFLOW_KIT = {
        **settings.WORKFLOW_KIT,
        "ATTACHMENT_ALLOWED_CONTENT_TYPES": ["application/pdf"],
    }
    with pytest.raises(AttachmentError):
        add_attachment(
            execution,
            upload=SimpleUploadedFile("evil.txt", b"x", content_type="text/plain"),
            user=_user("sec_emp4", "Employee"),
        )


def test_attachments_do_not_expose_storage_url_by_default(execution):
    """REST responses hide direct storage URLs unless explicitly enabled."""
    from workflow_kit.attachments.service import add_attachment

    attachment = add_attachment(
        execution,
        upload=SimpleUploadedFile("receipt.pdf", b"%PDF", content_type="application/pdf"),
        user=_user("sec_emp5", "Employee"),
    )
    response = _client_for(_user("sec_emp5", "Employee")).get(
        f"/api/executions/{execution.pk}/attachments/"
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == attachment.pk
    assert data[0]["url"] == ""


def test_attachments_expose_storage_url_when_opted_in(execution, settings):
    """With ``ATTACHMENT_PUBLIC_URLS`` enabled the URL is returned again."""
    from workflow_kit.attachments.service import add_attachment

    add_attachment(
        execution,
        upload=SimpleUploadedFile("receipt.pdf", b"%PDF", content_type="application/pdf"),
        user=_user("sec_emp6", "Employee"),
    )
    settings.WORKFLOW_KIT = {**settings.WORKFLOW_KIT, "ATTACHMENT_PUBLIC_URLS": True}
    response = _client_for(_user("sec_emp6", "Employee")).get(
        f"/api/executions/{execution.pk}/attachments/"
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()[0]["url"].endswith(".pdf")
    assert "receipt" in response.json()[0]["url"]


# -- #22/#23: admin and version immutability ------------------------------------


def test_admin_is_read_only_for_all_models(sec_workflow, execution):
    """Every registered model refuses add/change/delete through the admin."""
    from django.contrib.admin.sites import AdminSite
    from workflow_kit.admin import (
        ApprovalAdmin,
        WorkflowAttachmentAdmin,
        WorkflowCommentAdmin,
        WorkflowDelegationAdmin,
        WorkflowEventAdmin,
        WorkflowExecutionAdmin,
        WorkflowVersionAdmin,
    )
    from workflow_kit.models import (
        Approval,
        WorkflowAttachment,
        WorkflowComment,
        WorkflowDelegation,
        WorkflowEvent,
        WorkflowExecution,
        WorkflowVersion,
    )

    site = AdminSite()
    admins = [
        ApprovalAdmin(Approval, site),
        WorkflowExecutionAdmin(WorkflowExecution, site),
        WorkflowEventAdmin(WorkflowEvent, site),
        WorkflowCommentAdmin(WorkflowComment, site),
        WorkflowAttachmentAdmin(WorkflowAttachment, site),
        WorkflowDelegationAdmin(WorkflowDelegation, site),
        WorkflowVersionAdmin(WorkflowVersion, site),
    ]
    for admin in admins:
        assert admin.has_add_permission(None) is False  # type: ignore[arg-type]
        assert admin.has_change_permission(None) is False  # type: ignore[arg-type]
        assert admin.has_delete_permission(None) is False  # type: ignore[arg-type]


def test_non_staff_user_is_denied_admin(sec_workflow, execution):
    client = Client()
    user = _user("sec_nonstaff", is_staff=False)
    client.force_login(user)
    response = client.get("/admin/workflow_kit/workflowexecution/")
    assert response.status_code in (302, 403)


def test_published_version_cannot_be_mutated_through_orm():
    """Published workflow versions are immutable, even via direct ORM saves."""
    from workflow_kit import WorkflowVersionError
    from workflow_kit.engine.versioning import ensure_workflow_version
    from workflow_kit.models import VersionStatus

    workflow = Workflow(
        name="sec_version",
        initial="draft",
        states=["draft", "approved"],
        transitions=[("approve", "draft", "approved")],
        register=True,
    )
    version = ensure_workflow_version(workflow, changelog="init")
    assert version.status == VersionStatus.PUBLISHED
    version.version = 999
    with pytest.raises(WorkflowVersionError):
        version.save()

    registry.unregister("sec_version")
