"""Attachment public API.

Re-exports the attachment service so applications can
``from workflow_kit.attachments import add_attachment, execution_attachments``.
"""

from workflow_kit.attachments.service import (
    add_attachment,
    attachment_slug,
    execution_attachments,
)

__all__ = ["add_attachment", "execution_attachments", "attachment_slug"]
