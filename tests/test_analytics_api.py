"""Phase 12 tests: the REST analytics API.

The analytics endpoints are read-only and gated by :class:`IsAnalyticsViewer`
(authenticated staff, or holders of ``workflow_kit.view_analytics``). These
tests verify the permission surface, the endpoint responses against known
data, query-parameter handling, and that invalid arguments map to 400.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from tests.analytics_helpers import manager, run, set_due_at, set_timestamps
from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db

ANALYTICS_URLS = [
    "/api/analytics/metrics/",
    "/api/analytics/completion/",
    "/api/analytics/state_duration/",
    "/api/analytics/bottlenecks/",
    "/api/analytics/approvals/",
    "/api/analytics/approval_totals/",
    "/api/analytics/sla/",
    "/api/analytics/escalations/",
    "/api/analytics/versions/",
]


def _invoice(number: str):
    return Invoice.objects.create(number=number, amount="100.00", vendor="Acme")


def _plain_user():
    User = get_user_model()
    return User.objects.create_user(username="plain-user", password="pw")


def _staff_user():
    User = get_user_model()
    return User.objects.create_user(username="staff-analyst", password="pw", is_staff=True)


def _permitted_user():
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    User = get_user_model()
    user = User.objects.create_user(username="perm-analyst", password="pw")
    content_type, _ = ContentType.objects.get_or_create(
        app_label="workflow_kit",
        model="analytics",
    )
    permission, _ = Permission.objects.get_or_create(
        codename="view_analytics",
        content_type=content_type,
        defaults={"name": "Can view workflow analytics"},
    )
    user.user_permissions.add(permission)
    return user


@pytest.fixture(autouse=True)
def _dataset(analytics_workflow):
    """One approved, one pending-overdue and one running execution."""
    mgr = manager()
    approved = analytics_workflow.start(_invoice("INV-API-1"))
    run(approved, "submit", "approve", user=mgr)
    set_timestamps(
        approved,
        started_at=timezone.now() - timedelta(hours=2),
        completed_at=timezone.now() - timedelta(hours=1),
    )

    pending = analytics_workflow.start(_invoice("INV-API-2"))
    run(pending, "submit", user=mgr)
    set_due_at(pending, timezone.now() - timedelta(hours=1))

    analytics_workflow.start(_invoice("INV-API-3"))


def test_analytics_requires_authentication():
    response = APIClient().get("/api/analytics/metrics/")
    assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


def test_analytics_denies_plain_users():
    client = APIClient()
    client.force_authenticate(_plain_user())
    for url in ANALYTICS_URLS:
        response = client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN


def test_analytics_allows_staff():
    client = APIClient()
    client.force_authenticate(_staff_user())
    for url in ANALYTICS_URLS:
        response = client.get(url)
        assert response.status_code == status.HTTP_200_OK, url


def _perm_client() -> APIClient:
    client = APIClient()
    user = _permitted_user()
    client.force_authenticate(user)
    return client


def test_metrics_endpoint_returns_counts():
    response = _perm_client().get("/api/analytics/metrics/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["started"] == 3
    assert data["active"] == 2
    assert data["completed"] == 1
    assert data["sla_breached"] == 1


def test_completion_endpoint_returns_stats():
    data = _perm_client().get("/api/analytics/completion/").json()
    assert data["total"] == 3
    assert data["completed"] == 1
    assert data["duration"]["count"] == 1


def test_approval_totals_endpoint_with_group_by():
    data = _perm_client().get("/api/analytics/approval_totals/?group_by=status").json()
    by_status = {row["status"]: row for row in data}
    assert by_status["APPROVED"]["approved"] == 1
    assert by_status["PENDING"]["pending"] == 1


def test_sla_endpoint_reports_overdue():
    data = _perm_client().get("/api/analytics/sla/?workflow=analytics_flow").json()
    assert data["tracked"] == 1
    assert data["pending_overdue"] == 1
    assert data["breached"] == 1


def test_filter_and_scope_parameters_take_effect():
    client = _perm_client()
    data = client.get("/api/analytics/metrics/?state=review").json()
    assert data["started"] == 1
    data = client.get("/api/analytics/metrics/?state=draft").json()
    assert data["started"] == 1


def test_invalid_version_returns_400():
    response = _perm_client().get("/api/analytics/metrics/?version=abc")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["error"] == "invalid_analytics_arguments"


def test_invalid_date_returns_400():
    response = _perm_client().get("/api/analytics/completion/?start=nope")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_unknown_group_by_returns_400():
    response = _perm_client().get("/api/analytics/approval_totals/?group_by=who")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
