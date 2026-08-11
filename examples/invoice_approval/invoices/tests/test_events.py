"""Demo tests for the events and notification wiring.

The Invoice demo subscribes event handlers at app startup (``apps.py.ready``).
These tests verify that the engine's events are observable from the demo and
that a completed workflow triggers the demo email notification.
"""

import pytest
from django.core import mail
from workflow_kit import EventType
from workflow_kit.events import default_dispatcher, subscribe

from invoices.services import approve_invoice, create_invoice, submit_invoice

pytestmark = pytest.mark.django_db


def _completed_invoice(demo_users):
    invoice = create_invoice(number="INV-EV1", customer_name="Acme", amount="500.00")
    submit_invoice(invoice, user=demo_users["employee"])
    approve_invoice(invoice, user=demo_users["manager"])
    approve_invoice(invoice, user=demo_users["finance"])
    return invoice


def test_workflow_events_are_observed_by_demo_handler(demo_users):
    seen = []
    unsubscribe = subscribe(str(EventType.WORKFLOW_COMPLETED), seen.append)
    try:
        _completed_invoice(demo_users)
    finally:
        unsubscribe()

    assert len(seen) == 1
    event = seen[0]
    assert event.type == EventType.WORKFLOW_COMPLETED
    assert event.workflow == "invoice_approval"
    assert event.object.display == "INV-EV1"
    assert event.source_state == "finance_review"
    assert event.target_state == "approved"


def test_demo_email_notification_sent_on_completion(demo_users, settings):
    settings.MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}

    _completed_invoice(demo_users)

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["demo@example.invalid"]
    assert "INV-EV1" in message.subject
    assert "completed" in message.subject
    assert "Workflow: invoice_approval" in message.body


def test_events_are_dispatched_from_the_default_dispatcher(demo_users):
    listener = []
    unsub = default_dispatcher.subscribe(str(EventType.WORKFLOW_TRANSITIONED), listener.append)
    try:
        _completed_invoice(demo_users)
    finally:
        unsub()

    types = [str(e.type) for e in listener]
    assert types.count("workflow.transitioned") == 3
    assert types == [
        "workflow.transitioned",
        "workflow.transitioned",
        "workflow.transitioned",
    ]
