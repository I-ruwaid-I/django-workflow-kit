"""REST error handling for Django Workflow Kit.

The API is a thin layer over the workflow engine: every domain exception raised
by the engine is mapped to a stable, structured JSON error. Python stack traces
are never exposed to clients.
"""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from workflow_kit.analytics.base import AnalyticsError
from workflow_kit.exceptions import (
    ApprovalNotPendingError,
    ConditionFailedError,
    InvalidTransitionError,
    PermissionDeniedError,
    WorkflowAlreadyCompletedError,
)


class WorkflowApiError(Exception):
    """A REST-level error carrying an HTTP status and a stable error code."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def workflow_error_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Map workflow engine exceptions to structured API errors.

    Unknown exceptions fall through to DRF's default handler so standard
    authentication/permission errors keep their normal DRF representation.
    """
    mapping: dict[type[Exception], tuple[int, str]] = {
        InvalidTransitionError: (
            status.HTTP_409_CONFLICT,
            "invalid_transition",
        ),
        PermissionDeniedError: (
            status.HTTP_403_FORBIDDEN,
            "permission_denied",
        ),
        AnalyticsError: (
            status.HTTP_400_BAD_REQUEST,
            "invalid_analytics_arguments",
        ),
        ConditionFailedError: (
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "condition_failed",
        ),
        WorkflowAlreadyCompletedError: (
            status.HTTP_409_CONFLICT,
            "workflow_completed",
        ),
        ApprovalNotPendingError: (
            status.HTTP_409_CONFLICT,
            "approval_not_pending",
        ),
    }
    if isinstance(exc, PermissionDeniedError) or type(exc) in mapping:
        http_status, code = mapping.get(
            type(exc),
            (
                status.HTTP_409_CONFLICT,
                "workflow_error",
            ),
        )
        return Response(
            {
                "error": code,
                "message": str(exc),
            },
            status=http_status,
        )
    return exception_handler(exc, context)
