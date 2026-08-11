"""DRF analytics endpoints for the workflow REST API (Phase 12).

A thin HTTP layer over the :mod:`workflow_kit.analytics` Python API. All
endpoints are read-only and gated by :class:`IsAnalyticsViewer`, so ordinary
users cannot view aggregate workflow data unless they are staff or hold the
``workflow_kit.view_analytics`` permission.

Every action accepts the same query parameters:

* ``workflow`` — workflow name;
* ``version`` — workflow definition version number;
* ``start`` / ``end`` — ISO-8601 date range (timezone aware);
* ``state`` — current state (or approval step for approval-scoped endpoints);
* ``group_by`` — approval grouping dimension (approval-totals);
* ``threshold`` — bottleneck flag threshold (bottlenecks).
"""

from __future__ import annotations

from typing import Any

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from workflow_kit.analytics import (
    approval_metrics,
    approval_totals,
    bottlenecks,
    completion_metrics,
    escalation_analytics,
    execution_metrics,
    sla_metrics,
    state_durations,
    version_analytics,
)


class IsAnalyticsViewer(BasePermission):
    """Allow authenticated staff members or holders of the analytics permission.

    Analytics expose aggregate business information, so the default policy keeps
    them out of ordinary users' hands. Operators can grant the
    ``workflow_kit.view_analytics`` permission to specific users or groups.
    """

    def has_permission(self, request: Any, view: Any) -> bool:
        user = request.user
        return bool(
            user is not None
            and user.is_authenticated
            and (user.is_staff or user.has_perm("workflow_kit.view_analytics"))
        )


class WorkflowAnalyticsViewSet(viewsets.GenericViewSet[Any]):
    """Read-only analytics over executions, approvals, SLA and versions."""

    permission_classes = [IsAuthenticated, IsAnalyticsViewer]

    def _filters(self) -> dict[str, Any]:
        params = self.request.query_params
        filters: dict[str, Any] = {
            "workflow": params.get("workflow") or None,
            "workflow_version": params.get("version") or None,
            "start": params.get("start") or None,
            "end": params.get("end") or None,
            "state": params.get("state") or None,
        }
        return filters

    def _approval_filters(self) -> dict[str, Any]:
        filters = self._filters()
        step = self.request.query_params.get("step")
        if step:
            filters["state"] = step
        return filters

    def _scope_filters(self) -> dict[str, Any]:
        """Return the filters without the ``state`` dimension (spans cross states)."""
        return {key: value for key, value in self._filters().items() if key not in ("state",)}

    # -- Execution analytics --------------------------------------------------

    @action(detail=False, methods=["get"])
    def metrics(self, request: Any) -> Response:
        """Aggregate execution counts (started/active/completed/...)."""
        return Response(execution_metrics(**self._filters()).to_dict())

    @action(detail=False, methods=["get"])
    def completion(self, request: Any) -> Response:
        """Completion-time statistics over the filtered executions."""
        return Response(completion_metrics(**self._filters()).to_dict())

    @action(detail=False, methods=["get"])
    def state_duration(self, request: Any) -> Response:
        """How long executions spend in each state."""
        rows = state_durations(**self._scope_filters())
        return Response([row.to_dict() for row in rows])

    @action(detail=False, methods=["get"])
    def bottlenecks(self, request: Any) -> Response:
        """State durations ranked by average time, flagging disproportionate ones."""
        threshold = self.request.query_params.get("threshold", "1.25")
        rows = bottlenecks(**self._scope_filters(), threshold=float(threshold))
        return Response([row.to_dict() for row in rows])

    # -- Approval analytics ---------------------------------------------------

    @action(detail=False, methods=["get"])
    def approvals(self, request: Any) -> Response:
        """Aggregate approval counts and decision-time statistics."""
        return Response(approval_metrics(**self._approval_filters()).to_dict())

    @action(detail=False, methods=["get"])
    def approval_totals(self, request: Any) -> Response:
        """Approval counts grouped by ``group_by`` (workflow/version/step/approver/status)."""
        group_by = self.request.query_params.get("group_by", "workflow")
        rows = approval_totals(**self._approval_filters(), group_by=group_by)
        return Response(rows)

    # -- SLA / escalation analytics ------------------------------------------

    @action(detail=False, methods=["get"])
    def sla(self, request: Any) -> Response:
        """SLA compliance, breaches and overdue statistics."""
        return Response(sla_metrics(**self._approval_filters()).to_dict())

    @action(detail=False, methods=["get"])
    def escalations(self, request: Any) -> Response:
        """Escalation distribution and average escalation delay."""
        return Response(escalation_analytics(**self._scope_filters()))

    # -- Version analytics ----------------------------------------------------

    @action(detail=False, methods=["get"])
    def versions(self, request: Any) -> Response:
        """Per-version execution analytics."""
        rows = version_analytics(
            workflow=self._filters().get("workflow"),
            start=self._filters().get("start"),
            end=self._filters().get("end"),
        )
        return Response([row.to_dict() for row in rows])
