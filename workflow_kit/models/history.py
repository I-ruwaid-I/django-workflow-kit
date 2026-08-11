"""ORM model for the workflow audit history.

:class:`WorkflowEvent` is the append-only history record for every important
workflow action. The timeline is derived from these records rather than from a
second, independent history system.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models


class WorkflowEventType(models.TextChoices):
    """Stable event type codes recorded in the audit trail."""

    WORKFLOW_STARTED = "workflow_started", "Workflow started"
    TRANSITION_EXECUTED = "transition_executed", "Transition executed"
    APPROVAL_REQUIRED = "approval_required", "Approval required"
    APPROVAL_APPROVED = "approval_approved", "Approval approved"
    APPROVAL_REJECTED = "approval_rejected", "Approval rejected"
    APPROVAL_CANCELLED = "approval_cancelled", "Approval cancelled"
    APPROVAL_ESCALATED = "approval_escalated", "Approval escalated"
    APPROVAL_DELEGATED = "approval_delegated", "Approval delegated"
    DELEGATION_REVOKED = "delegation_revoked", "Delegation revoked"
    COMMENT_ADDED = "comment_added", "Comment added"
    ATTACHMENT_ADDED = "attachment_added", "Attachment added"
    WORKFLOW_COMPLETED = "workflow_completed", "Workflow completed"
    WORKFLOW_CANCELLED = "workflow_cancelled", "Workflow cancelled"


class WorkflowEvent(models.Model):
    """An immutable, append-only record of a workflow event.

    Records are created through :func:`workflow_kit.audit.service.record_event`
    while workflow actions execute. Once persisted, an event cannot be modified
    through the ORM: its ``save()`` method rejects updates to existing rows so
    historical truth is preserved.
    """

    execution = models.ForeignKey(
        "workflow_kit.WorkflowExecution",
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(
        max_length=40,
        choices=WorkflowEventType.choices,
        db_index=True,
    )
    action = models.CharField(max_length=100, blank=True)
    source_state = models.CharField(max_length=100, blank=True)
    target_state = models.CharField(max_length=100, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="wk_events",
    )
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["execution", "-created_at"]),
            models.Index(fields=["execution", "event_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type}: {self.action or self.source_state} -> {self.target_state}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Refuse to update an existing event so the audit trail stays append-only."""
        from workflow_kit.exceptions import AuditError

        if self.pk is not None:
            raise AuditError("Workflow event records are immutable and cannot be updated.")
        return super().save(*args, **kwargs)
