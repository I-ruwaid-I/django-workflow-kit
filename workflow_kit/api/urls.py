"""URL configuration for the optional workflow REST API.

Include this in a project that has ``djangorestframework`` installed::

    from django.urls import include, path

    urlpatterns = [
        path("workflow/", include("workflow_kit.api.urls")),
    ]

The router exposes:

    GET   /workflow/executions/
    GET   /workflow/executions/{id}/
    GET   /workflow/executions/{id}/actions/
    POST  /workflow/executions/{id}/transition/
    GET   /workflow/executions/{id}/history/
    GET   /workflow/executions/{id}/timeline/
    GET   /workflow/executions/{id}/approvals/
    GET   /workflow/executions/{id}/comments/
    POST  /workflow/executions/{id}/comments/
    GET   /workflow/executions/{id}/attachments/
    POST  /workflow/executions/{id}/attachments/
    GET   /workflow/versions/
    GET   /workflow/versions/{id}/
    GET   /workflow/analytics/metrics/
    GET   /workflow/analytics/completion/
    GET   /workflow/analytics/state_duration/
    GET   /workflow/analytics/bottlenecks/
    GET   /workflow/analytics/approvals/
    GET   /workflow/analytics/approval_totals/
    GET   /workflow/analytics/sla/
    GET   /workflow/analytics/escalations/
    GET   /workflow/analytics/versions/
"""

from __future__ import annotations

from django.urls import include, path
from rest_framework import routers

from workflow_kit.api.analytics_views import WorkflowAnalyticsViewSet
from workflow_kit.api.views import WorkflowExecutionViewSet, WorkflowVersionViewSet

router = routers.DefaultRouter()
router.register(r"executions", WorkflowExecutionViewSet, basename="execution")
router.register(r"versions", WorkflowVersionViewSet, basename="workflow-version")
router.register(r"analytics", WorkflowAnalyticsViewSet, basename="analytics")

urlpatterns = [
    path("", include(router.urls)),
]

app_name = "workflow_kit_api"
