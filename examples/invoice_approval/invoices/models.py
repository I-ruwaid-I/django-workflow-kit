from django.db import models

from .workflow import invoice_workflow


class Invoice(models.Model):
    """A business invoice that requires workflow approval.

    The invoice's workflow state is owned by the ``invoice_approval``
    ``Workflow`` definition and its :class:`WorkflowExecution`, never by a
    status column on this model.
    """

    number = models.CharField(max_length=100, unique=True)
    customer_name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        permissions = [
            ("can_finalize_invoice", "Can finalize an approved invoice"),
            ("can_reject_invoice", "Can reject an invoice in review"),
        ]

    def __str__(self) -> str:
        return self.number

    @property
    def execution(self):
        """The workflow execution running against this invoice."""
        return invoice_workflow.get_execution(self)

    @property
    def current_state(self) -> str:
        """The current workflow state of this invoice."""
        return self.execution.current_state

    @property
    def current_state_label(self) -> str:
        """The human-readable label of the current workflow state."""
        return self.execution.state_label

    def available_actions(self, user=None) -> list[str]:
        """Return the workflow actions currently available for this invoice."""
        return self.execution.available_actions(user=user)
