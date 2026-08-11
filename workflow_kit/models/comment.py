"""ORM models for workflow comments.

Comments let participants discuss an execution. A comment is tied to a single
execution, optionally records who wrote it and is surfaced through the
timeline as a ``comment_added`` audit event so discussion is part of the
execution's history.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class WorkflowComment(models.Model):
    """A comment attached to a workflow execution.

    Comments are created through :func:`workflow_kit.comments.service.add_comment`
    and listed through :func:`workflow_kit.comments.service.execution_comments`.
    ``metadata`` carries the execution's workflow version at the time of writing
    so a discussion stays legible even after newer versions exist.
    """

    execution = models.ForeignKey(
        "workflow_kit.WorkflowExecution",
        on_delete=models.CASCADE,
        related_name="comments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="wk_comments",
    )
    text = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["execution", "-created_at"]),
        ]

    def __str__(self) -> str:
        author = self.user.get_username() if self.user else "anonymous"
        snippet = self.text if len(self.text) <= 40 else f"{self.text[:37]}..."
        return f"comment by {author}: {snippet}"

    @property
    def author_label(self) -> str:
        """A stable label for the comment's author, or ``anonymous`` if absent."""
        if self.user is None:
            return "anonymous"
        get_username = getattr(self.user, "get_username", None)
        if callable(get_username):
            return get_username() or "anonymous"
        return str(self.user)
