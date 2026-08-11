"""ORM model for approval delegation (Phase 9).

A :class:`WorkflowDelegation` grants one user (the *grantee*) the right to
decide a step that would otherwise belong to the *granter*. Delegation is
scoped to an execution and optionally to a single step (an empty ``step``
applies to every pending approval of the execution). Only active, unexpired
delegations are honoured; expired delegations stay on disk for the audit
trail but never authorize a decision.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone


class WorkflowDelegation(models.Model):
    """A grant forwarding one user's approval right to another."""

    execution = models.ForeignKey(
        "workflow_kit.WorkflowExecution",
        on_delete=models.CASCADE,
        related_name="delegations",
    )
    granter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="wk_delegations_given",
    )
    grantee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wk_delegations",
    )
    step = models.CharField(max_length=100, blank=True, db_index=True)
    reason = models.TextField(blank=True)
    active = models.BooleanField(default=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["execution", "active"]),
            models.Index(fields=["grantee", "active"]),
        ]

    def __str__(self) -> str:
        return f"{self.execution} {self.granter} -> {self.grantee} [{self.step or '*'}]"

    @property
    def is_active(self) -> bool:
        """True while the delegation has not been revoked or expired."""
        if not self.active:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()

    def revoke(self, *, user: Any | None = None, reason: str = "") -> None:
        """Deactivate this delegation and record the audit trail."""
        self.active = False
        self.reason = reason or self.reason
        self.save(update_fields=["active", "reason", "updated_at"])
        from workflow_kit.audit.service import record_event

        record_event(
            self.execution,
            event_type="delegation_revoked",
            action="revoke",
            source_state=self.execution.current_state,
            target_state=self.execution.current_state,
            user=user,
            reason="",
            metadata={"delegation": self.pk, "grantee": self.grantee_id},
        )
