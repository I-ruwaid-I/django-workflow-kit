"""ORM models for the demo test app.

``Invoice`` is a realistic test model used by the workflow test suite and the
example application. The workflow kit itself must remain fully independent
from any particular business model.
"""

from django.db import models


class Invoice(models.Model):
    """A typical business document that requires workflow approval."""

    number = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    vendor = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["number"]

    def __str__(self) -> str:
        return self.number
