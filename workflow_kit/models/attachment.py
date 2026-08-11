"""ORM models for workflow attachments.

Attachments let participants attach files to an execution (receipts, signed
documents, screenshots). Files are stored through Django's storage abstraction
(``FileField``), so swapping storage backends later does not touch callers.
Metadata about the upload (original name, content type, size) is persisted for
listing and audit without re-reading the stored file.
"""

from __future__ import annotations

import os

from django.conf import settings
from django.db import models


def attachment_upload_path(attachment: WorkflowAttachment, filename: str) -> str:
    """Directory per attachment id inside the workflow's media namespace."""
    return os.path.join("workflow_kit", "attachments", str(attachment.pk or "new"), filename)


class WorkflowAttachment(models.Model):
    """A file attached to a workflow execution.

    Uploads are created through :func:`workflow_kit.attachments.service.add_attachment`.
    The file is persisted to the default storage backend; ``name``, ``content_type``
    and ``size`` are captured at upload time and retained for listing.
    """

    execution = models.ForeignKey(
        "workflow_kit.WorkflowExecution",
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="wk_attachments",
    )
    file = models.FileField(upload_to=attachment_upload_path)
    name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255, blank=True)
    size = models.BigIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["execution", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} on {self.execution}"

    @property
    def extension(self) -> str:
        """The file extension without the leading dot, lower-cased."""
        return os.path.splitext(self.name)[1].lstrip(".").lower()
