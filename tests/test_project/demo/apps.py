"""Demo app containing realistic business models for the test suite."""

from django.apps import AppConfig


class DemoConfig(AppConfig):
    """Application configuration for the demo app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "tests.test_project.demo"
    label = "demo"
