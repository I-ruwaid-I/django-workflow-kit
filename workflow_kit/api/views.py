"""DRF views for the workflow REST API.

Everything here is a thin pass-through to the existing workflow engine and its
services: transition execution, permissions, conditions, approvals, history and
timeline all come from the package's Python API. The views add only HTTP
mechanics (authentication, serialization, error mapping).
"""

from __future__ import annotations

from typing import Any

from django.http import Http404
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from workflow_kit.api.pagination import WorkflowKitPagination
from workflow_kit.api.serializers import (
    ActionSerializer,
    ApprovalSerializer,
    AttachmentCreateSerializer,
    AttachmentSerializer,
    AuditEventSerializer,
    CommentCreateSerializer,
    CommentSerializer,
    DelegateSerializer,
    EscalationSerializer,
    TimelineEventSerializer,
    TransitionSerializer,
    WorkflowExecutionDetailSerializer,
    WorkflowExecutionSerializer,
    WorkflowVersionSerializer,
)
from workflow_kit.models import Approval, WorkflowExecution, WorkflowVersion


class WorkflowVersionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[WorkflowVersion],
):
    """Read workflow definition versions (Phase 9)."""

    queryset = WorkflowVersion.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowVersionSerializer
    pagination_class = WorkflowKitPagination

    def get_queryset(self) -> Any:
        queryset = super().get_queryset()
        workflow = self.request.query_params.get("workflow")
        status_value = self.request.query_params.get("status")
        if workflow is not None:
            queryset = queryset.filter(workflow=workflow)
        if status_value is not None:
            queryset = queryset.filter(status=status_value.upper())
        return queryset


class WorkflowExecutionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[WorkflowExecution],
):
    """Read and act on workflow executions through DRF."""

    queryset = WorkflowExecution.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowExecutionSerializer
    pagination_class = WorkflowKitPagination

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Any]]:
        if self.action == "retrieve":
            return WorkflowExecutionDetailSerializer
        return WorkflowExecutionSerializer

    def get_queryset(self) -> Any:
        queryset = super().get_queryset().select_related("content_type", "workflow_version")
        for field in ("workflow", "current_state", "completed"):
            queryset = self._apply_filter(queryset, field)
        return queryset

    def _apply_filter(self, queryset: Any, field: str) -> Any:
        value = self.request.query_params.get(field)
        if value is None:
            return queryset
        if field == "workflow":
            return queryset.filter(workflow_name=value)
        if field == "current_state":
            return queryset.filter(current_state=value)
        if field == "completed":
            return queryset.filter(completed_at__isnull=not _truthy(value))
        return queryset

    def get_object(self) -> WorkflowExecution:
        """Resolve the execution by ``pk`` with ``get_object_or_404`` semantics."""
        queryset = self.get_queryset()
        try:
            obj = queryset.get(pk=self.kwargs["pk"])
        except (WorkflowExecution.DoesNotExist, ValueError) as exc:
            raise Http404("No WorkflowExecution matches the given query.") from exc
        self.check_object_permissions(self.request, obj)
        if not isinstance(obj, WorkflowExecution):
            raise Http404("No WorkflowExecution matches the given query.")
        return obj

    # -- Actions -------------------------------------------------------------

    @action(detail=True, methods=["get"])
    def actions(self, request: Request, pk: int) -> Response:
        execution = self.get_object()
        from workflow_kit.api.actions import available_actions

        serializer = ActionSerializer(available_actions(execution, user=request.user), many=True)
        return Response({"actions": serializer.data})

    # -- Transition ----------------------------------------------------------

    @action(detail=True, methods=["post"])
    def transition(self, request: Request, pk: int) -> Response:
        execution = self.get_object()
        serializer = TransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]
        reason = serializer.validated_data.get("reason", "")
        previous_state = execution.current_state

        result = self._apply_action(execution, action, user=request.user, reason=reason)

        response = {
            "id": execution.pk,
            "action": action,
            "previous_state": previous_state,
            "current_state": result.current_state,
            "is_completed": result.is_completed,
        }
        return Response(response, status=status.HTTP_200_OK)

    def _apply_action(
        self, execution: WorkflowExecution, action: str, *, user: Any, reason: str
    ) -> WorkflowExecution:
        if action == "approve":
            execution.approve(user=user, reason=reason)
        elif action == "reject":
            execution.reject(user=user, reason=reason)
        else:
            execution.transition(action, user=user)
        return execution

    # -- History / timeline / approvals --------------------------------------

    @action(detail=True, methods=["get"])
    def history(self, request: Request, pk: int) -> Response:
        execution = self.get_object()
        events = execution.history().select_related("user")
        return Response(AuditEventSerializer(events, many=True).data)

    @action(detail=True, methods=["get"])
    def timeline(self, request: Request, pk: int) -> Response:
        execution = self.get_object()
        return Response(TimelineEventSerializer(execution.timeline(), many=True).data)  # type: ignore[arg-type]

    @action(detail=True, methods=["get"])
    def approvals(self, request: Request, pk: int) -> Response:
        execution = self.get_object()
        approvals = Approval.objects.filter(execution=execution).select_related(
            "execution", "approver"
        )
        return Response(ApprovalSerializer(approvals, many=True).data)

    # -- Delegation / escalation (Phase 9) -----------------------------------

    @action(detail=True, methods=["post"])
    def delegate(self, request: Request, pk: int) -> Response:
        """Forward a step's approval right from the caller to ``grantee``."""
        execution = self.get_object()
        serializer = DelegateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        grantee = _resolve_user_by_username(data["grantee"])
        delegation = execution.delegate(
            granter=request.user,
            grantee=grantee,
            reason=data.get("reason", ""),
            step=data.get("step", ""),
        )
        return Response(
            {"id": delegation.pk, "step": delegation.step, "grantee": data["grantee"]},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def escalate(self, request: Request, pk: int) -> Response:
        """Escalate the current step to ``approver`` (group or username)."""
        execution = self.get_object()
        serializer = EscalationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        approval = execution.escalate(
            data["approver"],
            user=request.user,
            reason=data.get("reason", ""),
        )
        return Response(
            {"id": approval.pk, "step": approval.step, "mode": approval.mode},
            status=status.HTTP_200_OK,
        )

    # -- Comments / attachments (Phase 10) ------------------------------------

    @action(detail=True, methods=["get", "post"])
    def comments(self, request: Request, pk: int) -> Response:
        """List comments on an execution, or attach a new one."""
        execution = self.get_object()
        if request.method == "POST":
            serializer = CommentCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            comment = execution.add_comment(
                user=request.user,
                text=serializer.validated_data["text"],
            )
            response_serializer = CommentSerializer(comment)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        comments = execution.comments.select_related("user").order_by("created_at", "id")
        return Response(CommentSerializer(comments, many=True).data)

    @action(
        detail=True,
        methods=["get", "post"],
        parser_classes=[MultiPartParser, FormParser],
    )
    def attachments(self, request: Request, pk: int) -> Response:
        """List attachments on an execution, or upload a new one."""
        execution = self.get_object()
        if request.method == "POST":
            serializer = AttachmentCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            upload = serializer.validated_data["file"]
            attachment = execution.add_attachment(
                upload=upload,
                name=serializer.validated_data.get("name") or None,
                user=request.user,
            )
            response_serializer = AttachmentSerializer(attachment)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        attachments = execution.attachments.select_related("uploaded_by").order_by(
            "created_at", "id"
        )
        return Response(AttachmentSerializer(attachments, many=True).data)


def _truthy(value: str) -> bool:
    """Interpret a query-string boolean (``true``/``1``/``yes``)."""
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_user_by_username(username: str) -> Any:
    """Resolve a user by username for delegation, 404 if unknown."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        return User.objects.get(username=username)
    except User.DoesNotExist as exc:
        raise Http404(f"No user with username {username!r}.") from exc
