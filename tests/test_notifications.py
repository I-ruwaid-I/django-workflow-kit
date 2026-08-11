"""Phase 5 tests: the notification providers and router.

Notifications are a consumer of domain events: a router subscribes to event
types and forwards them to providers (email, webhook). This file verifies the
payloads, the signing, the enable/disable configuration and the end-to-end
routing behavior without any real network or SMTP involvement.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from django.core import mail
from workflow_kit import DomainEvent, EventType, ObjectRef
from workflow_kit.events import EventDispatcher, dispatch
from workflow_kit.notifications import (
    EmailProvider,
    NotificationError,
    NotificationProvider,
    NotificationRouter,
    WebhookProvider,
    sign_payload,
)

pytestmark = pytest.mark.django_db


def _event(type_: EventType = EventType.WORKFLOW_COMPLETED, **overrides) -> DomainEvent:
    fields = dict(
        type=type_,
        workflow="invoice_approval",
        execution_id=12,
        object=ObjectRef(app_label="invoices", model_name="invoice", pk=99, display="INV-1"),
        actor="sarah",
        timestamp=datetime(2026, 2, 3, 4, 5, tzinfo=UTC),
        source_state="finance_review",
        target_state="approved",
        action="approve",
        metadata={"reason": "looks good"},
        id="abc123",
    )
    fields.update(overrides)
    return DomainEvent(**fields)


# -- email provider ------------------------------------------------


def test_email_provider_sends_to_recipients(settings):
    settings.MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
    settings.WORKFLOW_KIT = {
        **settings.WORKFLOW_KIT,
        "EMAIL_NOTIFICATIONS_ENABLED": True,
        "EMAIL_SUBJECT_PREFIX": "[Workflow] ",
        "EMAIL_FROM": None,
    }
    provider = EmailProvider(recipients=lambda event: [f"owner@{event.object.display}.test"])
    assert provider.send(_event()) is True
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["owner@INV-1.test"]
    assert message.subject == "[Workflow] INV-1 completed"
    body = message.body
    assert "Workflow: invoice_approval" in body
    assert "Object: INV-1" in body
    assert "Actor: sarah" in body
    assert "Reason: looks good" in body


def test_email_provider_disabled_skips(settings):
    settings.WORKFLOW_KIT = dict(settings.WORKFLOW_KIT, EMAIL_NOTIFICATIONS_ENABLED=False)
    provider = EmailProvider(recipients=lambda event: ["a@example.test"])
    with patch("django.core.mail.send_mail") as send:
        assert provider.send(_event()) is False
        send.assert_not_called()


def test_email_provider_subject_and_body_override(settings):
    settings.MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
    provider = EmailProvider(
        recipients=["a@example.test"],
        subject_fn=lambda event: f"Custom {event.object.display}",
        body_fn=lambda event: f"Body for {event.workflow}",
    )
    assert provider.send(_event()) is True
    message = mail.outbox[0]
    assert message.subject == "Custom INV-1"
    assert message.body == "Body for invoice_approval"


def test_email_provider_no_recipients_skips(settings):
    settings.MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
    provider = EmailProvider(recipients=None)
    with patch("django.core.mail.send_mail") as send:
        assert provider.send(_event()) is False
        send.assert_not_called()


def test_email_provider_exposes_from_email(settings):
    settings.MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
    settings.WORKFLOW_KIT = {
        **settings.WORKFLOW_KIT,
        "EMAIL_FROM": "workflow@example.test",
    }
    provider = EmailProvider(recipients=["a@example.test"])
    assert provider.send(_event()) is True
    assert mail.outbox[0].from_email == "workflow@example.test"


# -- webhook provider ---------------------------------------------------------


def test_webhook_payload_structure(settings):
    settings.WORKFLOW_KIT = {
        **settings.WORKFLOW_KIT,
        "WEBHOOK_SECRET": "sekret",
        "WEBHOOK_URL": "http://example.test/hook",
    }
    payload = WebhookProvider().payload(_event())
    assert payload["event"] == "workflow.completed"
    assert payload["id"] == "abc123"
    assert payload["workflow"] == "invoice_approval"
    assert payload["execution_id"] == 12
    assert payload["object"] == {
        "type": "invoices.invoice",
        "id": 99,
        "display": "INV-1",
    }
    assert payload["actor"] == "sarah"
    assert payload["source_state"] == "finance_review"
    assert payload["target_state"] == "approved"
    assert payload["data"] == {"reason": "looks good"}


def test_webhook_payload_is_json_safe(settings):
    settings.WORKFLOW_KIT = {
        **settings.WORKFLOW_KIT,
        "WEBHOOK_SECRET": "sekret",
        "WEBHOOK_URL": "http://example.test/hook",
    }
    payload = WebhookProvider().payload(_event())
    assert json.loads(json.dumps(payload)) == payload


def test_webhook_signature_hmac_binds_timestamp_event_and_body(settings):
    settings.WORKFLOW_KIT = {
        **settings.WORKFLOW_KIT,
        "WEBHOOK_SECRET": "sekret",
        "WEBHOOK_URL": "http://example.test/hook",
    }
    provider = WebhookProvider()
    event = _event()
    url, body, headers = provider._prepare(event)
    expected = sign_payload("sekret", headers["X-Domain-Timestamp"], event.id, body)
    assert headers["X-Domain-Signature"] == expected
    assert headers["X-Domain-Event"] == "workflow.completed"
    assert headers["X-Domain-Event-Id"] == event.id
    assert url == "http://example.test/hook"


def test_webhook_disabled_by_default():
    provider = WebhookProvider()
    with patch("urllib.request.urlopen") as urlopen:
        assert provider.send(_event()) is False
        urlopen.assert_not_called()


def test_webhook_requires_url(settings):
    settings.WORKFLOW_KIT = {**settings.WORKFLOW_KIT, "WEBHOOK_NOTIFICATIONS_ENABLED": True}
    provider = WebhookProvider()
    with pytest.raises(NotificationError):
        provider.send(_event())


def test_webhook_post_success(settings):
    settings.WORKFLOW_KIT = {
        **settings.WORKFLOW_KIT,
        "WEBHOOK_NOTIFICATIONS_ENABLED": True,
    }
    provider = WebhookProvider()
    with (
        patch(
            "workflow_kit.notifications.webhook.workflow_settings.WEBHOOK_URL",
            "http://example.test/hook",
        ),
        patch("urllib.request.urlopen") as urlopen,
    ):
        response = urlopen.return_value.__enter__.return_value
        response.status = 200
        assert provider.send(_event()) is True
        assert urlopen.call_count == 1


def test_webhook_failure_raises_notification_error(settings):
    settings.WORKFLOW_KIT = {
        **settings.WORKFLOW_KIT,
        "WEBHOOK_NOTIFICATIONS_ENABLED": True,
        "WEBHOOK_URL": "http://example.test/hook",
    }
    provider = WebhookProvider()
    with (
        patch("urllib.request.urlopen", side_effect=OSError("connection refused")),
        pytest.raises(NotificationError),
    ):
        provider.send(_event())


# -- notification router -------------------------------------------------------


class RecordingProvider(NotificationProvider):
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def send(self, event: DomainEvent) -> bool:
        self.events.append(event)
        return True


def test_router_forwards_events_to_provider():
    from workflow_kit.events import default_dispatcher

    provider = RecordingProvider()
    router = NotificationRouter(dispatcher=default_dispatcher)
    router.register(provider, event_type="workflow.completed")
    router.install()
    try:
        dispatch(_event())
        assert len(provider.events) == 1
        assert provider.events[0].type == EventType.WORKFLOW_COMPLETED
    finally:
        router.uninstall()


def test_router_only_forwards_matching_events():
    provider = RecordingProvider()
    dispatcher = EventDispatcher()
    router = NotificationRouter(dispatcher=dispatcher)
    router.register(provider, event_type="workflow.completed")
    router.install()
    try:
        dispatcher.dispatch(_event(type=EventType.APPROVAL_CREATED))
        assert provider.events == []
    finally:
        router.uninstall()


def test_router_provider_failure_is_isolated():
    class _Boom(NotificationProvider):
        def send(self, event: DomainEvent) -> bool:
            raise NotificationError("nope")

    dispatcher = EventDispatcher()
    router = NotificationRouter(dispatcher=dispatcher)
    router.register(_Boom(), event_type="workflow.completed")
    router.install()
    try:
        dispatcher.dispatch(_event())
    finally:
        router.uninstall()
    # No exception escaped; the router swallowed the provider failure.


def test_router_requires_provider_instance():
    from workflow_kit.events import EventDispatcher

    router = NotificationRouter(dispatcher=EventDispatcher())
    with pytest.raises(TypeError):
        router.register(object(), event_type="workflow.completed")  # type: ignore[arg-type]


def test_router_clear_unsubscribes_and_drops():
    provider = RecordingProvider()
    dispatcher = EventDispatcher()
    router = NotificationRouter(dispatcher=dispatcher)
    router.register(provider, event_type="workflow.completed")
    router.install()
    router.clear()
    dispatcher.dispatch(_event())
    assert provider.events == []
