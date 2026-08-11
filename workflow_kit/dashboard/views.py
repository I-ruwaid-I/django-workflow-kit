"""Dashboard views (Phase 13, Part B).

Every view is a thin consumer of the existing engine / analytics / service
layers. No analytics calculation is duplicated here; the dashboard renders the
same numbers the REST analytics API exposes.

Security:
    * ``LoginRequiredMixin`` on every view;
    * analytics aggregates gated by :class:`~workflow_kit.api.analytics_views
      .IsAnalyticsViewer` (staff or ``workflow_kit.view_analytics``), re-used
      verbatim from the REST API so the two surfaces never disagree;
    * execution-level data is resolved through the engine's own permissions and
      the approval assignment records — a user only ever sees the pending work
      they are genuinely allowed to decide.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.generic import TemplateView

from workflow_kit.analytics import (
    approval_metrics,
    bottlenecks,
    completion_metrics,
    escalation_analytics,
    execution_metrics,
    sla_metrics,
    state_durations,
    version_analytics,
)
from workflow_kit.models import (
    Approval,
    ApprovalStatus,
    WorkflowDelegation,
    WorkflowExecution,
    WorkflowVersion,
)

from .mixins import AnalyticsViewerMixin

_PAGE_SIZE = 25


def _rate(numerator: int, denominator: int) -> float | None:
    """Return ``numerator/denominator * 100`` or ``None`` when undefined."""
    if not denominator:
        return None
    return round(numerator / denominator * 100, 1)


def _assignment_matches(approval: Approval, user: Any) -> bool:
    """Return whether ``user`` may fill the pending ``approval`` slot."""
    assignment = approval.assignment or {}
    kind = assignment.get("type")
    if kind == "any":
        return True
    if kind == "user":
        return assignment.get("username") == getattr(user, "username", None)
    if kind == "group":
        group = assignment.get("name")
        if not group:
            return False
        return bool(user.groups.filter(name=group).exists())
    return False


def _pending_approvals_for(user: Any) -> list[Approval]:
    """Return the pending approvals the current user may decide."""
    approvals = Approval.objects.filter(status=ApprovalStatus.PENDING).select_related(
        "execution", "execution__content_type", "execution__workflow_version"
    )
    return [approval for approval in approvals if _assignment_matches(approval, user)]


class DashboardHomeView(LoginRequiredMixin, TemplateView):
    """Overview: headline metrics + workflow health (PHASE13 ``#35``-``#36``).

    Aggregate metrics are gated to analytics viewers (staff or the
    ``workflow_kit.view_analytics`` permission). Non-viewers still get a real
    Overview page: a permission notice plus their own pending actions, so the
    link always responds instead of silently redirecting.
    """

    template_name = "workflow_kit/dashboard/overview.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        assert user.is_authenticated
        viewer = user.is_staff or user.has_perm("workflow_kit.view_analytics")
        context["can_view_analytics"] = viewer
        context["pending_actions"] = len(_pending_approvals_for(user))
        if viewer:
            context["metrics"] = execution_metrics().to_dict()
            context["sla"] = sla_metrics().to_dict()
            context["escalations"] = escalation_analytics()
            context["workflow_health"] = self._workflow_health()
        context["page"] = "overview"
        return context

    def _workflow_health(self) -> list[dict[str, Any]]:
        """Per-workflow active count, completion rate and SLA compliance.

        Built from the analytics layer (``version_analytics`` + ``sla_metrics``)
        so the numbers always agree with the REST analytics API.
        """
        rows: list[dict[str, Any]] = []
        for version_row in version_analytics():
            workflow = version_row.workflow
            if any(row["workflow"] == workflow for row in rows):
                rows = [
                    {
                        **row,
                        "active": row["active"] + version_row.active,
                        "started": row["started"] + version_row.started,
                        "completed": row["completed"] + version_row.completed,
                    }
                    if row["workflow"] == workflow
                    else row
                    for row in rows
                ]
                continue
            rows.append(
                {
                    "workflow": workflow,
                    "started": version_row.started,
                    "active": version_row.active,
                    "completed": version_row.completed,
                }
            )
        for row in rows:
            sla_row = sla_metrics(workflow=row["workflow"])
            row["completion_rate"] = _rate(row["completed"], row["started"])
            row["sla_rate"] = sla_row.compliance_rate
        return rows


class MyWorkView(LoginRequiredMixin, TemplateView):
    """The current user's pending approvals and delegated work (``#37``)."""

    template_name = "workflow_kit/dashboard/my_work.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        assert user.is_authenticated
        now = timezone.now()
        pending = _pending_approvals_for(user)

        delegated = (
            WorkflowDelegation.objects.filter(
                grantee=user,
                active=True,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .select_related("execution", "granter")
        )

        context["pending_approvals"] = pending
        context["delegations"] = delegated
        context["page"] = "my_work"
        return context


class ExecutionListView(LoginRequiredMixin, TemplateView):
    """Searchable, filterable, paginated execution listing (``#39``)."""

    template_name = "workflow_kit/dashboard/executions.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        workflow = params.get("workflow", "").strip()
        state = params.get("state", "").strip()
        version = params.get("version", "").strip()
        status = params.get("status", "").strip()
        search = params.get("q", "").strip()

        queryset = WorkflowExecution.objects.select_related("content_type", "workflow_version")
        if workflow:
            queryset = queryset.filter(workflow_name=workflow)
        if state:
            queryset = queryset.filter(current_state=state)
        if version:
            queryset = queryset.filter(workflow_version__version=int(version))
        if status == "active":
            queryset = queryset.filter(completed_at__isnull=True)
        elif status == "completed":
            queryset = queryset.filter(completed_at__isnull=False)
        if search:
            queryset = queryset.filter(
                Q(workflow_name__icontains=search)
                | Q(current_state__icontains=search)
                | Q(id__icontains=search)
            )

        workflows = sorted(set(WorkflowExecution.objects.values_list("workflow_name", flat=True)))
        paginator = Paginator(queryset, _PAGE_SIZE)
        page = paginator.get_page(params.get("page"))

        context["executions"] = page
        context["workflows"] = workflows
        context["filters"] = {
            "workflow": workflow,
            "state": state,
            "version": version,
            "status": status,
            "q": search,
        }
        context["page"] = "executions"
        return context


class ExecutionDetailView(LoginRequiredMixin, TemplateView):
    """Full detail: state, version, SLA, graph, timeline, audit (``#40``-``#46``)."""

    template_name = "workflow_kit/dashboard/execution_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        execution = get_object_or_404(
            WorkflowExecution.objects.select_related("content_type", "workflow_version"),
            pk=kwargs["pk"],
        )
        context["execution"] = execution
        context["approvals"] = execution.approvals.select_related("approver").order_by(
            "created_at", "id"
        )
        context["events"] = (
            execution.history().select_related("user").order_by("-created_at", "-id")
        )
        context["timeline"] = execution.timeline()
        context["comments"] = execution.comments.select_related("user").order_by("created_at", "id")
        context["attachments"] = execution.attachments.select_related("uploaded_by").order_by(
            "created_at", "id"
        )
        context["versions"] = WorkflowVersion.objects.filter(
            workflow=execution.workflow_name
        ).order_by("-version")
        context["page"] = "executions"
        return context


class AnalyticsView(AnalyticsViewerMixin, LoginRequiredMixin, TemplateView):
    """Aggregate analytics screens (``#49``-``#51``)."""

    template_name = "workflow_kit/dashboard/analytics.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        workflow = params.get("workflow", "").strip() or None
        context["metrics"] = execution_metrics(workflow=workflow).to_dict()
        context["completion"] = completion_metrics(workflow=workflow).to_dict()
        context["state_durations"] = [row.to_dict() for row in state_durations(workflow=workflow)]
        context["bottlenecks"] = [row.to_dict() for row in bottlenecks(workflow=workflow)]
        context["approvals"] = approval_metrics(workflow=workflow).to_dict()
        context["sla"] = sla_metrics(workflow=workflow).to_dict()
        context["escalations"] = escalation_analytics(workflow=workflow)
        context["versions"] = [row.to_dict() for row in version_analytics(workflow=workflow)]
        context["workflow_filter"] = workflow
        context["workflow_choices"] = sorted(
            {row["workflow"] for row in WorkflowVersion.objects.values("workflow")}
        )
        context["page"] = "analytics"
        return context
