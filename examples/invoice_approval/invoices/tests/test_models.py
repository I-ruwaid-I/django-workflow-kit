"""Tests for the Invoice model."""

import pytest
from django.db import IntegrityError

from invoices.services import create_invoice

pytestmark = pytest.mark.django_db


def test_create_invoice_starts_workflow_at_draft():
    invoice = create_invoice(number="INV-1", customer_name="Acme", amount="1500.00")
    assert invoice.current_state == "draft"
    assert invoice.current_state_label == "Draft"
    assert invoice.execution.is_completed is False


def test_invoice_number_is_unique():
    create_invoice(number="INV-2", customer_name="Acme", amount="100.00")
    with pytest.raises(IntegrityError):
        create_invoice(number="INV-2", customer_name="Globex", amount="100.00")


def test_invoice_str_returns_number():
    invoice = create_invoice(number="INV-3", customer_name="Acme", amount="100.00")
    assert str(invoice) == "INV-3"


def test_invoice_defaults_description_blank():
    invoice = create_invoice(number="INV-4", customer_name="Acme", amount="1.00")
    assert invoice.description == ""
