"""Django application configuration for Django Workflow Kit."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class WorkflowKitConfig(AppConfig):
    """Application configuration for the ``workflow_kit`` Django app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "workflow_kit"
    label = "workflow_kit"
    verbose_name = _("Workflow Kit")

    def ready(self) -> None:
        """Install the structured observability bridge when enabled.

        The observer subscribes to the existing domain event dispatcher and
        records structured log records; it never changes workflow behaviour.
        Controlled by ``WORKFLOW_KIT["STRUCTURED_LOGGING"]`` (default True).
        """
        from django.conf import settings as django_settings

        from workflow_kit.observability import install_structured_logging

        config = getattr(django_settings, "WORKFLOW_KIT", {})
        if config.get("STRUCTURED_LOGGING", True):
            install_structured_logging()
