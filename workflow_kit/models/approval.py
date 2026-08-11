"""ORM models for the approval subsystem.

The approval engine is layered on top of the existing workflow engine: the
workflow transition system remains the single source of truth for state
changes, and :class:`Approval` records persist the per-step approval
requirements and their decisions.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class ApprovalStatus(models.TextChoices):
    """Stable internal status values for an approval."""

    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


class ApprovalMode(models.TextChoices):
    """The voting mode a pending approval participates in."""

    ALL = "ALL", "All"
    ANY = "ANY", "Any"
    QUORUM = "QUORUM", "Quorum"


class Approval(models.Model):
    """A single approval requirement scoped to one workflow step.

    One or more ``Approval`` records are created for each non-terminal step an
    execution enters, according to the step's approval requirement (Phase 9).
    ``mode`` records the requirement's voting mode, ``order`` the slot among
    parallel approvals and ``assignment`` who may fill the slot
    (``{"type": "any"|"group"|"user"}``). The execution advances out of the
    step when the requirement is satisfied; the status is immutable once
    decided and the decision is recorded atomically with the state change.
    """

    execution = models.ForeignKey(
        "workflow_kit.WorkflowExecution",
        on_delete=models.CASCADE,
        related_name="approvals",
    )
    step = models.CharField(max_length=100)
    status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
        db_index=True,
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="wk_approvals",
    )
    delegation = models.ForeignKey(
        "workflow_kit.WorkflowDelegation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approvals",
    )
    mode = models.CharField(
        max_length=20,
        choices=ApprovalMode.choices,
        default=ApprovalMode.ALL,
        db_index=True,
    )
    order = models.PositiveIntegerField(default=1)
    assignment = models.JSONField(default=dict, blank=True)
    allow_self = models.BooleanField(default=True)
    due_at = models.DateTimeField(null=True, blank=True)
    action = models.CharField(max_length=100, blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["execution", "status"]),
            models.Index(fields=["execution", "step"]),
            models.Index(fields=["status", "due_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.execution} [{self.step}] {self.status}"

    @property
    def is_decided(self) -> bool:
        """True once the approval has been decided (or cancelled)."""
        return self.status != ApprovalStatus.PENDING

    @property
    def is_pending(self) -> bool:
        """True while the approval still awaits a decision."""
        return self.status == ApprovalStatus.PENDING

    @property
    def is_overdue(self) -> bool:
        """True when the approval is still pending past its SLA deadline."""
        if not self.is_pending or self.due_at is None:
            return False
        from django.utils import timezone

        return self.due_at < timezone.now()

    @property
    def mode_label(self) -> str:
        """A human-friendly name for the voting mode."""
        return dict(ApprovalMode.choices).get(self.mode, self.mode)
