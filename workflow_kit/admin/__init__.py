"""Django admin integration for workflow executions.

Read-oriented registration so developers can inspect executions, approvals and
the audit trail. It intentionally exposes no actions that could bypass workflow
authorization: decisions are only possible through the public engine API.
"""

from typing import Any

from django.contrib import admin
from django.urls import path

from workflow_kit.models import (
    Approval,
    WorkflowAttachment,
    WorkflowComment,
    WorkflowDelegation,
    WorkflowEvent,
    WorkflowExecution,
    WorkflowVersion,
)


@admin.register(WorkflowExecution)
class WorkflowExecutionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin view for workflow executions."""

    list_display = (
        "workflow_name",
        "workflow_version",
        "object_id",
        "initiated_by",
        "current_state",
        "started_at",
        "completed_at",
    )
    list_filter = ("workflow_name", "current_state")
    readonly_fields = (
        "workflow_name",
        "workflow_version",
        "content_type",
        "object_id",
        "initiated_by",
        "current_state",
        "started_at",
        "updated_at",
        "completed_at",
    )

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    # -- Phase 12: read-only analytics summary --------------------------------

    def get_urls(self) -> list[Any]:
        """Add a read-only ``summary`` page alongside the standard admin URLs."""
        urlpatterns = super().get_urls()
        summary = [
            path(
                "summary/",
                self.admin_site.admin_view(self.summary_view),
                name="workflow_kit_workflowexecution_summary",
            ),
        ]
        return summary + urlpatterns

    def summary_view(self, request: Any) -> Any:
        """Render aggregate workflow metrics (read-only analyst summary).

        The page is served by the admin site's own view wrapper, so the usual
        staff/superuser admin rules apply and it never writes to the database.
        """
        from django.shortcuts import render

        from workflow_kit.analytics import completion_metrics, execution_metrics

        rows: list[dict[str, Any]] = []
        registered = sorted(
            {
                name
                for (name,) in WorkflowExecution.objects.order_by()
                .values_list("workflow_name")
                .distinct()
            }
        )
        for name in registered:
            metrics = execution_metrics(workflow=name)
            completion = completion_metrics(workflow=name)
            rows.append(
                {
                    "workflow": name,
                    "started": metrics.started,
                    "active": metrics.active,
                    "completed": metrics.completed,
                    "rejected": metrics.rejected,
                    "cancelled": metrics.cancelled,
                    "failed": metrics.failed,
                    "escalated": metrics.escalated,
                    "sla_breached": metrics.sla_breached,
                    "average_completion_seconds": completion.duration.average,
                }
            )
        rows.sort(key=lambda row: row["workflow"].lower())
        return render(
            request,
            "workflow_kit/admin/analytics_summary.html",
            {
                "title": "Workflow analytics",
                "rows": rows,
                "site_header": self.admin_site.site_header,
            },
        )


@admin.register(Approval)
class ApprovalAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin view for approval requirements and their decisions."""

    list_display = (
        "execution",
        "step",
        "status",
        "mode",
        "order",
        "action",
        "approver",
        "due_at",
        "created_at",
        "updated_at",
    )
    list_filter = ("status", "mode", "step")
    search_fields = ("execution__object_id", "reason", "approver__username")
    readonly_fields = (
        "execution",
        "step",
        "status",
        "mode",
        "order",
        "assignment",
        "allow_self",
        "due_at",
        "approver",
        "delegation",
        "action",
        "reason",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(WorkflowDelegation)
class WorkflowDelegationAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Read-only admin view for approval delegations."""

    list_display = (
        "execution",
        "granter",
        "grantee",
        "step",
        "active",
        "expires_at",
        "created_at",
    )
    list_filter = ("active", "step")
    search_fields = ("execution__object_id", "granter__username", "grantee__username")
    readonly_fields = (
        "execution",
        "granter",
        "grantee",
        "step",
        "reason",
        "active",
        "expires_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(WorkflowEvent)
class WorkflowEventAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Read-only admin view for the append-only audit trail."""

    list_display = (
        "execution",
        "event_type",
        "action",
        "source_state",
        "target_state",
        "user",
        "created_at",
    )
    list_filter = ("event_type",)
    search_fields = ("execution__object_id", "action", "reason")
    readonly_fields = (
        "execution",
        "event_type",
        "action",
        "source_state",
        "target_state",
        "user",
        "reason",
        "metadata",
        "created_at",
    )

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(WorkflowComment)
class WorkflowCommentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Read-only admin view for execution comments."""

    list_display = ("execution", "user", "created_at")
    list_filter = ("created_at",)
    search_fields = ("execution__object_id", "user__username", "text")
    readonly_fields = ("execution", "user", "text", "metadata", "created_at")

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(WorkflowAttachment)
class WorkflowAttachmentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Read-only admin view for execution attachments."""

    list_display = ("execution", "name", "content_type", "size", "uploaded_by", "created_at")
    list_filter = ("created_at",)
    search_fields = ("execution__object_id", "uploaded_by__username", "name")
    readonly_fields = (
        "execution",
        "uploaded_by",
        "file",
        "name",
        "content_type",
        "size",
        "metadata",
        "created_at",
    )

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(WorkflowVersion)
class WorkflowVersionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Read-only admin view for immutable workflow definition versions.

    Published and retired versions are immutable through the ORM; this admin
    intentionally exposes no path to change or delete them. Draft definitions
    can be inspected here and published programmatically through the public API.
    """

    list_display = (
        "workflow",
        "version",
        "status",
        "created_by",
        "created_at",
        "published_at",
        "retired_at",
    )
    list_filter = ("status", "workflow")
    search_fields = ("workflow", "changelog")
    readonly_fields = (
        "workflow",
        "version",
        "status",
        "definition",
        "changelog",
        "created_by",
        "created_at",
        "updated_at",
        "published_at",
        "retired_at",
    )

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False
