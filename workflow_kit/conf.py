"""Configuration handling for Django Workflow Kit.

Settings are read from the ``WORKFLOW_KIT`` dict in the Django settings module.
The package provides sensible defaults, so basic usage requires little or no
configuration.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings as django_settings

_DEFAULTS: dict[str, Any] = {
    # When True, workflow transitions run inside a database transaction.
    "ATOMIC_TRANSITIONS": True,
    # Phase 5 -- notifications (events are always emitted).
    "NOTIFICATIONS_ENABLED": True,
    # Phase 12 -- structured observability: log every domain event with a
    # JSON-friendly payload (event, workflow, version, execution, correlation).
    "STRUCTURED_LOGGING": True,
    # Email notification provider configuration.
    "EMAIL_NOTIFICATIONS_ENABLED": True,
    # MAILERS alias used for workflow notification emails (Django >= 6.1).
    "EMAIL_MAILER": "default",
    # From address for workflow notification emails; falls back to
    # settings.DEFAULT_FROM_EMAIL when None.
    "EMAIL_FROM": None,
    # Subject line used for event emails before the event label/action.
    "EMAIL_SUBJECT_PREFIX": "[Workflow] ",
    # Webhook notification provider configuration.
    "WEBHOOK_NOTIFICATIONS_ENABLED": False,
    "WEBHOOK_URL": "",
    "WEBHOOK_SECRET": "",
    # Phase 13 -- attachment security policy.
    # Maximum accepted upload size in bytes (0 disables the limit).
    "ATTACHMENT_MAX_SIZE": 0,
    # Allowed upload content types as an allow-list of ``"type/subtype"``
    # strings (empty disables the type check).
    "ATTACHMENT_ALLOWED_CONTENT_TYPES": [],
    # Whether REST responses may expose the stored file's direct storage URL.
    # Keep False so private attachments are not reachable through predictable
    # storage URLs; host applications should serve files behind their own
    # authorization instead.
    "ATTACHMENT_PUBLIC_URLS": False,
}

_IMPORT_STRINGS: tuple[str, ...] = ()


class WorkflowKitSettings:
    """Proxy over ``WORKFLOW_KIT`` Django settings with package defaults."""

    def __init__(self, defaults: dict[str, Any] | None = None) -> None:
        self._defaults = defaults or _DEFAULTS

    def __getattr__(self, name: str) -> Any:
        overrides = getattr(django_settings, "WORKFLOW_KIT", {})
        if name in self._defaults:
            value = overrides.get(name, self._defaults[name])
            return value
        raise AttributeError(f"'WORKFLOW_KIT' setting does not define '{name}'")


settings = WorkflowKitSettings()
