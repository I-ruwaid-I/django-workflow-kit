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
        """Install the structured observability bridge and the automation hook.

        The observer subscribes to the existing domain event dispatcher and
        records structured log records; it never changes workflow behaviour.
        The automation hook evaluates WHEN/IF/THEN rules against every domain
        event. Both are controlled by ``WORKFLOW_KIT`` settings.
        """
        from django.conf import settings as django_settings

        from workflow_kit.observability import install_structured_logging

        config = getattr(django_settings, "WORKFLOW_KIT", {})
        if config.get("STRUCTURED_LOGGING", True):
            install_structured_logging()
        if config.get("AUTOMATION", True):
            from workflow_kit.automation import install

            install()