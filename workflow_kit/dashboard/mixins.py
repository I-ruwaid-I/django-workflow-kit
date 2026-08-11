"""Dashboard permission mixins."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.views.generic.base import View


class AnalyticsViewerMixin(View):
    """Require staff or the ``workflow_kit.view_analytics`` permission.

    Re-uses the same rule as the REST analytics API so the dashboard and the
    API never disagree about who may see aggregate workflow data.
    """

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        user = request.user
        if not (user is not None and user.is_authenticated):
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())
        if not (user.is_staff or user.has_perm("workflow_kit.view_analytics")):
            raise PermissionDenied("You do not have permission to view workflow analytics.")
        return super().dispatch(request, *args, **kwargs)
