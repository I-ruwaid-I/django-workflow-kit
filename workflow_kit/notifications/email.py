"""Email notification provider.

Uses Django's email infrastructure (``django.core.mail``) through the modern
``MAILERS`` configuration introduced in Django 6.1. The provider works with the
console mailer in development, the SMTP mailer in production and the locmem
mailer in tests — the backend is chosen by the host project's ``MAILERS``
setting, never by the package. No third-party dependency is required.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.core.mail import send_mail
from django.utils import timezone

from workflow_kit.conf import settings as workflow_settings
from workflow_kit.notifications.base import NotificationError, NotificationProvider

if TYPE_CHECKING:
    from workflow_kit.events.types import DomainEvent

logger = logging.getLogger(__name__)

_LABELS = {
    "workflow.started": "started",
    "workflow.transitioned": "moved to a new state",
    "workflow.completed": "completed",
    "workflow.cancelled": "cancelled",
    "workflow.rejected": "was rejected",
    "approval.created": "requires approval",
    "approval.approved": "was approved",
    "approval.rejected": "was rejected",
}


class EmailProvider(NotificationProvider):
    """Send a plain-text email for every event via ``django.core.mail``.

    ``recipients`` should be a callable receiving the event and returning the
    list of email addresses to notify. Subject and body can be overridden with
    ``subject_fn`` and ``body_fn`` (each receiving the event).
    """

    def __init__(
        self,
        recipients: Any,
        *,
        subject_fn: Any = None,
        body_fn: Any = None,
    ) -> None:
        self._recipients = recipients
        self._subject_fn = subject_fn
        self._body_fn = body_fn

    def send(self, event: DomainEvent) -> bool:
        """Send the event email, returning True on success."""
        if not workflow_settings.EMAIL_NOTIFICATIONS_ENABLED:
            logger.debug("Email notifications are disabled; skipping '%s'.", event.type)
            return False
        addresses = self._resolve_recipients(event)
        if not addresses:
            return False
        subject = self._subject(event)
        body = self._body(event)
        try:
            kwargs: dict[str, Any] = {
                "from_email": workflow_settings.EMAIL_FROM,
                "recipient_list": addresses,
            }
            # ``using`` selects the host project's ``MAILERS`` alias, available
            # only on Django >= 6.1. On earlier versions the default backend is
            # used, so the kwarg is omitted.
            if hasattr(send_mail, "kwargs") and "using" in getattr(
                send_mail, "__defaults__", ()
            ):
                kwargs["using"] = workflow_settings.EMAIL_MAILER
            send_mail(subject, body, **kwargs)
        except Exception as exc:  # noqa: BLE001 - surface as a domain error
            raise NotificationError(f"Email delivery failed: {exc}") from exc
        return True

    def _resolve_recipients(self, event: DomainEvent) -> list[str]:
        if self._recipients is None:
            return []
        if callable(self._recipients):
            return list(self._recipients(event))
        return list(self._recipients)

    def _subject(self, event: DomainEvent) -> str:
        if self._subject_fn is not None:
            return str(self._subject_fn(event))
        label = _LABELS.get(str(event.type), str(event.type))
        return f"{workflow_settings.EMAIL_SUBJECT_PREFIX}{event.object.display} {label}"

    def _body(self, event: DomainEvent) -> str:
        if self._body_fn is not None:
            return str(self._body_fn(event))
        return _render_default_body(event)


def _render_default_body(event: DomainEvent) -> str:
    label = _LABELS.get(str(event.type), str(event.type))
    lines = [
        f"Workflow: {event.workflow}",
    ]
    if event.workflow_version is not None:
        lines.append(f"Version: {event.workflow_version}")
    lines.append(f"Object: {event.object.display}")
    lines.append(f"Event: {label}")
    if event.actor:
        lines.append(f"Actor: {event.actor}")
    if event.source_state:
        lines.append(f"From: {event.source_state}")
    if event.target_state:
        lines.append(f"To: {event.target_state}")
    if event.metadata.get("reason"):
        lines.append(f"Reason: {event.metadata['reason']}")
    lines.append(f"Time: {timezone.localtime(event.timestamp).isoformat()}")
    return "\n".join(lines)
