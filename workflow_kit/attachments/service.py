"""Attachment service for workflow executions.

Attachments let participants attach files to an execution. Files are stored
through Django's storage abstraction (``FileField``), so the package works with
Django's default storage and any backend the hosting application configures
(S3, Azure, ...). Uploading an attachment records a ``attachment_added`` audit
event and emits a ``workflow.attachment_added`` domain event so the timeline
and external handlers observe the upload.
"""

from __future__ import annotations

import os
import posixpath
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from django.db.models import QuerySet
from django.utils.text import slugify

from workflow_kit.audit.service import _persistable_user, record_event
from workflow_kit.conf import settings as workflow_settings
from workflow_kit.events.service import emit_event
from workflow_kit.events.types import EventType
from workflow_kit.exceptions import AttachmentError
from workflow_kit.models.attachment import WorkflowAttachment
from workflow_kit.models.execution import WorkflowExecution
from workflow_kit.models.history import WorkflowEventType


def _validate_upload(upload: Any, *, name: str) -> None:
    """Enforce the package's attachment security policy (Phase 13).

    Checks the declared content type against the allow-list and the declared
    size against the configured cap. Raises :class:`AttachmentError` for
    disallowed uploads so private files never reach storage.
    """
    max_size = workflow_settings.ATTACHMENT_MAX_SIZE
    if max_size:
        size = getattr(upload, "size", 0) or 0
        if size > max_size:
            raise AttachmentError(
                f"Attachment '{name}' is {size} bytes, over the {max_size}-byte limit."
            )
    allowed = workflow_settings.ATTACHMENT_ALLOWED_CONTENT_TYPES
    if allowed:
        content_type = (getattr(upload, "content_type", "") or "").strip().lower()
        if content_type not in {entry.strip().lower() for entry in allowed}:
            raise AttachmentError(
                f"Attachment '{name}' has disallowed content type '{content_type or 'unknown'}'."
            )


def add_attachment(
    execution: WorkflowExecution,
    *,
    upload: UploadedFile[Any] | Any,
    name: str | None = None,
    user: Any = None,
    metadata: dict[str, Any] | None = None,
) -> WorkflowAttachment:
    """Persist ``upload`` as an attachment on ``execution``.

    ``upload`` is any file-like object with ``name`` and ``size`` attributes
    (an ``UploadedFile`` from a request, an ``InMemoryUploadedFile``, ...). The
    stored ``name`` defaults to the upload's original file name but can be
    overridden. The attachment is written through the default storage backend,
    recorded on the audit trail and emitted as a domain event.

    Uploads are validated against the configured security policy (size cap and
    content-type allow-list) and the persisted name is sanitized so it cannot
    escape the attachment directory.
    """
    original_name = name or getattr(upload, "name", None) or "attachment"
    stored_name = attachment_slug(original_name)
    _validate_upload(upload, name=stored_name)
    attachment = WorkflowAttachment.objects.create(
        execution=execution,
        uploaded_by=_persistable_user(user),
        file=upload,
        name=stored_name,
        content_type=getattr(upload, "content_type", ""),
        size=getattr(upload, "size", 0),
        metadata=dict(metadata or {}),
    )
    record_event(
        execution,
        event_type=WorkflowEventType.ATTACHMENT_ADDED,
        action="attachment",
        source_state=execution.current_state,
        user=user,
        metadata={
            "attachment_id": attachment.pk,
            "name": attachment.name,
            "size": attachment.size,
        },
    )
    emit_event(
        EventType.ATTACHMENT_ADDED,
        execution,
        workflow=execution.workflow_name,
        source_state=execution.current_state,
        action="attachment",
        user=user,
        metadata={
            "attachment_id": attachment.pk,
            "name": attachment.name,
            "size": attachment.size,
        },
    )
    return attachment


def execution_attachments(execution: WorkflowExecution) -> QuerySet[WorkflowAttachment]:
    """Return every attachment for ``execution``, oldest first."""
    return execution.attachments.select_related("uploaded_by").order_by("created_at", "id")


def attachment_slug(name: str) -> str:
    """Return a filesystem-safe slug for ``name``.

    The base name is slugified (dashes, path separators and control characters
    removed) and the original extension is kept, so stored file names can never
    contain ``..``, absolute paths or other path components.
    """
    base, ext = os.path.splitext(posixpath.basename((name or "").replace("\\", "/")))
    return f"{slugify(base) or 'attachment'}{ext}"
