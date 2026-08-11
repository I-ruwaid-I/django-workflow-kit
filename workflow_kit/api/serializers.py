"""DRF serializers for the workflow API.

The REST layer is a thin projection over the existing engine and models: it
exposes explicit, controlled fields and never dumps arbitrary database columns.
Business-object references are rendered as a safe ``{type, id}`` pair rather
than the full object.
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from workflow_kit.models import (
    Approval,
    WorkflowAttachment,
    WorkflowComment,
    WorkflowEvent,
    WorkflowExecution,
    WorkflowVersion,
)
from workflow_kit.timeline.event import TimelineEvent


def _object_ref(execution: WorkflowExecution) -> dict[str, Any]:
    return {
        "type": f"{execution.content_type.app_label}.{execution.content_type.model}",
        "id": execution.object_id,
    }


class WorkflowExecutionSerializer(serializers.ModelSerializer[WorkflowExecution]):
    """Compact representation used in list responses."""

    workflow = serializers.CharField(source="workflow_name", read_only=True)
    workflow_version = serializers.SerializerMethodField()
    state_label = serializers.CharField(read_only=True)
    is_completed = serializers.ReadOnlyField()
    object = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowExecution
        fields = [
            "id",
            "workflow",
            "workflow_version",
            "current_state",
            "state_label",
            "is_completed",
            "object",
            "started_at",
            "updated_at",
            "completed_at",
        ]

    def get_object(self, execution: WorkflowExecution) -> dict[str, Any]:
        return _object_ref(execution)

    def get_workflow_version(self, execution: WorkflowExecution) -> int | None:
        return execution.workflow_version_number


class WorkflowExecutionDetailSerializer(WorkflowExecutionSerializer):
    """Detailed representation including the caller's available actions."""

    available_actions = serializers.SerializerMethodField()

    class Meta(WorkflowExecutionSerializer.Meta):
        fields = WorkflowExecutionSerializer.Meta.fields + ["available_actions"]

    def get_available_actions(self, execution: WorkflowExecution) -> list[dict[str, str]]:
        request = self.context.get("request")
        user = getattr(request, "user", None) if request is not None else None
        from workflow_kit.api.actions import available_actions

        return available_actions(execution, user=user)


class TransitionSerializer(serializers.Serializer[str]):
    """Input for the transition endpoint."""

    action = serializers.CharField(max_length=100)
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class ActionSerializer(serializers.Serializer[Any]):
    """A single action available to the authenticated user."""

    name = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]


class AuditEventSerializer(serializers.ModelSerializer[WorkflowEvent]):
    """Structured audit event from the append-only history."""

    event = serializers.CharField(source="event_type", read_only=True)
    actor = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = WorkflowEvent
        fields = [
            "event",
            "actor",
            "timestamp",
            "source_state",
            "target_state",
            "action",
            "reason",
            "metadata",
        ]

    def get_actor(self, instance: WorkflowEvent) -> str | None:
        if instance.user is None:
            return None
        username = getattr(instance.user, "get_username", None)
        return username() if callable(username) else str(instance.user)


class TimelineEventSerializer(serializers.Serializer[TimelineEvent]):
    """A single timeline entry, derived from the audit trail."""

    event = serializers.CharField(source="event_type")
    label = serializers.CharField()  # type: ignore[assignment]
    actor = serializers.CharField(default=None)
    timestamp = serializers.DateTimeField()
    source_state = serializers.CharField(default="")
    target_state = serializers.CharField(default="")
    action = serializers.CharField(default="")
    reason = serializers.CharField(default="")
    metadata = serializers.JSONField(default=dict)

    def to_representation(self, instance: TimelineEvent) -> dict[str, Any]:
        return {
            "event": instance.event_type,
            "label": instance.label,
            "actor": instance.actor,
            "timestamp": instance.timestamp,
            "source_state": instance.source_state,
            "target_state": instance.target_state,
            "action": instance.action,
            "reason": instance.reason,
            "metadata": instance.metadata,
        }


class ApprovalSerializer(serializers.ModelSerializer[Approval]):
    """An approval requirement/decision for an execution."""

    step = serializers.CharField()
    status = serializers.CharField()
    mode = serializers.CharField()
    approver = serializers.SerializerMethodField()
    is_overdue = serializers.ReadOnlyField()

    class Meta:
        model = Approval
        fields = [
            "id",
            "step",
            "status",
            "mode",
            "order",
            "assignment",
            "approver",
            "action",
            "reason",
            "due_at",
            "is_overdue",
            "created_at",
            "updated_at",
        ]

    def get_approver(self, instance: Approval) -> str | None:
        if instance.approver is None:
            return None
        username = getattr(instance.approver, "get_username", None)
        return username() if callable(username) else str(instance.approver)


class DelegateSerializer(serializers.Serializer[str]):
    """Input for delegating an approval step."""

    grantee = serializers.CharField(max_length=150)
    step = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class EscalationSerializer(serializers.Serializer[str]):
    """Input for escalating the current step."""

    approver = serializers.CharField(max_length=150)
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class WorkflowVersionSerializer(serializers.ModelSerializer[WorkflowVersion]):
    """A persisted workflow definition version (Phase 9)."""

    created_by = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowVersion
        fields = [
            "id",
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
        ]
        read_only_fields = fields

    def get_created_by(self, instance: WorkflowVersion) -> str | None:
        if instance.created_by is None:
            return None
        username = getattr(instance.created_by, "get_username", None)
        return username() if callable(username) else str(instance.created_by)


class CommentSerializer(serializers.ModelSerializer[WorkflowComment]):
    """A comment on an execution (Phase 10)."""

    author = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowComment
        fields = ["id", "text", "author", "created_at"]

    def get_author(self, instance: WorkflowComment) -> str:
        return instance.author_label


class CommentCreateSerializer(serializers.Serializer[str]):
    """Input for attaching a comment to an execution."""

    text = serializers.CharField(max_length=5000, allow_blank=False)


class AttachmentSerializer(serializers.ModelSerializer[WorkflowAttachment]):
    """An attachment on an execution (Phase 10)."""

    url = serializers.SerializerMethodField()
    extension = serializers.CharField(read_only=True)

    class Meta:
        model = WorkflowAttachment
        fields = [
            "id",
            "name",
            "content_type",
            "size",
            "extension",
            "url",
            "created_at",
        ]

    def get_url(self, instance: WorkflowAttachment) -> str:
        from workflow_kit.conf import settings as workflow_settings

        if not workflow_settings.ATTACHMENT_PUBLIC_URLS:
            return ""
        try:
            return instance.file.url
        except ValueError:
            return ""


class AttachmentCreateSerializer(serializers.Serializer[Any]):
    """Input for uploading an attachment to an execution."""

    file = serializers.FileField()
    name = serializers.CharField(required=False, allow_blank=True, default="")
