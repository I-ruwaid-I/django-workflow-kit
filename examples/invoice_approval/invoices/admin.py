from django.contrib import admin

from .models import Invoice


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "customer_name",
        "amount",
        "workflow_state",
        "created_at",
    )
    search_fields = ("number", "customer_name")
    readonly_fields = ("workflow_state", "created_at", "updated_at")

    @admin.display(description="Current state", ordering="pk")
    def workflow_state(self, obj):
        return obj.current_state_label
