"""URL configuration for the Workflow Dashboard.

Include this in a project that has ``workflow_kit.dashboard`` in
``INSTALLED_APPS``::

    from django.urls import include, path

    urlpatterns = [
        path("dashboard/", include("workflow_kit.dashboard.urls")),
    ]
"""

from __future__ import annotations

from django.urls import path

from workflow_kit.dashboard import views

app_name = "workflow_kit_dashboard"

urlpatterns = [
    path("", views.DashboardHomeView.as_view(), name="overview"),
    path("my-work/", views.MyWorkView.as_view(), name="my_work"),
    path("executions/", views.ExecutionListView.as_view(), name="executions"),
    path(
        "executions/<int:pk>/",
        views.ExecutionDetailView.as_view(),
        name="execution_detail",
    ),
    path("analytics/", views.AnalyticsView.as_view(), name="analytics"),
]
