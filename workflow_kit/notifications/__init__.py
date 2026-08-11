"""Notification providers and router.

Notifications are a consumer of :mod:`workflow_kit.events`, never a concern of
the workflow engine. Email and webhook providers ship with the core; third
party channels (Slack, Teams...) can be added as their own providers without
modifying the engine.
"""

from workflow_kit.notifications.base import (
    Notification,
    NotificationError,
    NotificationProvider,
)
from workflow_kit.notifications.email import EmailProvider
from workflow_kit.notifications.router import NotificationRouter
from workflow_kit.notifications.webhook import WebhookProvider, sign_payload

__all__ = [
    "Notification",
    "NotificationError",
    "NotificationProvider",
    "NotificationRouter",
    "EmailProvider",
    "WebhookProvider",
    "sign_payload",
]
