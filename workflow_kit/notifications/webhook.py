"""Webhook notification provider.

Posts structured JSON events to a configured URL with an HMAC-SHA256 signature
over the payload. The payload deliberately contains only the public event
fields — never the full business object, credentials or internal data.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.request
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from workflow_kit.conf import settings as workflow_settings
from workflow_kit.notifications.base import NotificationError, NotificationProvider

if TYPE_CHECKING:
    from workflow_kit.events.types import DomainEvent

logger = logging.getLogger(__name__)


def sign_payload(secret: str, timestamp: str, event_id: str, body: str) -> str:
    """Return the HMAC-SHA256 signature for a webhook body.

    The signature authenticates the request and binds it to an exact payload,
    timestamp and event id so clients can detect tampering or replay.
    """
    message = f"{timestamp}.{event_id}.{body}"
    digest = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


class WebhookProvider(NotificationProvider):
    """POST a signed JSON representation of every event to ``workflow_settings.WEBHOOK_URL``."""

    def __init__(self) -> None:
        self._secret = workflow_settings.WEBHOOK_SECRET

    def send(self, event: DomainEvent) -> bool:
        """POST the signed event; return True when the endpoint responds ok."""
        if not workflow_settings.WEBHOOK_NOTIFICATIONS_ENABLED:
            logger.debug("Webhook notifications are disabled; skipping '%s'.", event.type)
            return False
        if not workflow_settings.WEBHOOK_URL:
            raise NotificationError("WEBHOOK_URL is required to deliver webhook notifications.")
        url, body, headers = self._prepare(event)
        try:
            request = urllib.request.Request(
                url,
                data=body.encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - configured URL
                status = int(response.status)
                return 200 <= status < 300
        except Exception as exc:  # noqa: BLE001 - surface as a domain error
            raise NotificationError(f"Webhook delivery failed: {exc}") from exc

    def payload(self, event: DomainEvent) -> dict[str, Any]:
        """Build the structured, JSON-safe webhook payload for ``event``."""
        return {
            "event": str(event.type),
            "id": event.id,
            "workflow": event.workflow,
            "workflow_version": event.workflow_version,
            "execution_id": event.execution_id,
            "object": event.object.to_dict(),
            "actor": event.actor,
            "timestamp": event.timestamp.isoformat(),
            "source_state": event.source_state,
            "target_state": event.target_state,
            "action": event.action,
            "data": event.metadata,
        }

    def _prepare(self, event: DomainEvent) -> tuple[str, str, Any]:
        payload = self.payload(event)
        body = json.dumps(payload, sort_keys=True)
        timestamp = timezone.now().isoformat()
        signature = sign_payload(self._secret, timestamp, event.id, body) if self._secret else ""
        headers = {
            "Content-Type": "application/json",
            "X-Domain-Event": str(event.type),
            "X-Domain-Event-Id": event.id,
            "X-Domain-Timestamp": timestamp,
        }
        if self._secret:
            headers["X-Domain-Signature"] = signature
        return workflow_settings.WEBHOOK_URL, body, headers
