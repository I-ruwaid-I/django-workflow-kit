"""Tests for the demo test models."""

import pytest
from django.db import IntegrityError

from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


def test_invoice_creation():
    invoice = Invoice.objects.create(number="INV-2001", amount="250.00", vendor="Globex")
    assert invoice.pk is not None
    assert str(invoice) == "INV-2001"


def test_invoice_number_is_unique():
    Invoice.objects.create(number="INV-9001", amount="1.00")
    with pytest.raises(IntegrityError):
        Invoice.objects.create(number="INV-9001", amount="2.00")


def test_invoice_ordering():
    Invoice.objects.create(number="B", amount="1.00")
    Invoice.objects.create(number="A", amount="1.00")
    assert list(Invoice.objects.all()) == list(Invoice.objects.order_by("number"))
