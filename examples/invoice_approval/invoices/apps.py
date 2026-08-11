from django.apps import AppConfig


class InvoicesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "invoices"
    verbose_name = "Invoices"

    def ready(self) -> None:
        from . import events  # noqa: PLC0415 - import after apps are loaded

        events.install()
