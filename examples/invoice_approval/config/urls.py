"""Root URL configuration for the Invoice Approval demo."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("invoices/", include("invoices.urls")),
    path("api/", include("workflow_kit.api.urls")),
    path("dashboard/", include("workflow_kit.dashboard.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
