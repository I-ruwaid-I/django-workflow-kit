"""Django application configuration for the Workflow Dashboard."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class WorkflowKitDashboardConfig(AppConfig):
    """Application configuration for ``workflow_kit.dashboard``.

    Add ``"workflow_kit.dashboard"`` to ``INSTALLED_APPS`` and include
    ``workflow_kit.dashboard.urls`` under a path of your choice to mount the
    dashboard. The app ships no models and performs no database writes.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "workflow_kit.dashboard"
    label = "workflow_kit_dashboard"
    verbose_name = _("Workflow Dashboard")
