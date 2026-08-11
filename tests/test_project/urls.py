"""URL configuration for the test project."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("workflow_kit.api.urls")),
    path("dashboard/", include("workflow_kit.dashboard.urls")),
]
