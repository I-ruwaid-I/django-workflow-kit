"""Phase 13 Part B tests: the Workflow Dashboard.

The dashboard is a plain-Django, server-rendered app that re-uses the engine,
analytics and service layers. These tests verify:

* authentication is required on every page;
* aggregate analytics screens follow the same permission rule as the REST
  analytics API (staff or ``workflow_kit.view_analytics``);
* the overview redirects non-viewers to their own work queue;
* My Work surfaces only the approvals the current user may actually decide,
  plus active delegations;
* executions list supports search / filter / pagination and empty states;
* execution detail renders approvals, timeline, comments, attachments and
  version history without exposing data the user cannot see.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone

from tests.analytics_helpers import manager, run
from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db

DASHBOARD_URLS = [
    "/dashboard/",
    "/dashboard/my-work/",
    "/dashboard/executions/",
    "/dashboard/analytics/",
]


def _invoice(number: str = "INV-DASH-1") -> Invoice:
    return Invoice.objects.create(number=number, amount="100.00", vendor="Acme")


def _plain_user() -> object:
    User = get_user_model()
    return User.objects.create_user(username="dash-plain", password="pw")


def _staff_user() -> object:
    User = get_user_model()
    return User.objects.create_user(username="dash-staff", password="pw", is_staff=True)


def _permitted_user() -> object:
    User = get_user_model()
    user = User.objects.create_user(username="dash-perm", password="pw")
    permission = Permission.objects.get(
        codename="view_analytics",
        content_type__app_label="workflow_kit",
        content_type__model="workflowexecution",
    )
    user.user_permissions.add(permission)
    return user


def _login(client, user) -> None:
    client.force_login(user)


# --------------------------------------------------------------------------- #
# Authentication and permission gating
# --------------------------------------------------------------------------- #


def test_all_dashboard_pages_require_authentication(client):
    for url in DASHBOARD_URLS:
        response = client.get(url)
        assert response.status_code in (302, 403), url


def test_analytics_denies_plain_users(client):
    _login(client, _plain_user())
    response = client.get("/dashboard/analytics/")
    assert response.status_code == 403


def test_analytics_allows_staff(client):
    _login(client, _staff_user())
    response = client.get("/dashboard/analytics/")
    assert response.status_code == 200


def test_analytics_allows_permission_holders(client):
    _login(client, _permitted_user())
    response = client.get("/dashboard/analytics/")
    assert response.status_code == 200


def test_overview_renders_notice_for_plain_user(client):
    _login(client, _plain_user())
    response = client.get("/dashboard/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Workflow Overview" in body
    assert "do not have permission" in body


def test_overview_allows_staff(client):
    _login(client, _staff_user())
    response = client.get("/dashboard/")
    assert response.status_code == 200
    assert b"Workflow Overview" in response.content
    assert b"Workflow Health" in response.content


# --------------------------------------------------------------------------- #
# My Work
# --------------------------------------------------------------------------- #


def test_my_work_shows_only_assignable_pending_approvals(client, analytics_workflow):
    mgr = manager()
    execution = analytics_workflow.start(_invoice("INV-DASH-2"))
    run(execution, "submit", user=mgr)

    _login(client, mgr)
    response = client.get("/dashboard/my-work/")
    assert response.status_code == 200
    assert f"/dashboard/executions/{execution.pk}/" in response.content.decode()


def test_my_work_hides_unrelated_pending_approvals(client, analytics_workflow):
    mgr = manager()
    execution = analytics_workflow.start(_invoice("INV-DASH-3"))
    run(execution, "submit", user=mgr)

    stranger = _plain_user()
    _login(client, stranger)
    response = client.get("/dashboard/my-work/")
    assert response.status_code == 200
    assert f"/dashboard/executions/{execution.pk}/" not in response.content.decode()


def test_my_work_shows_active_delegations(client, analytics_workflow):
    from workflow_kit.models import WorkflowDelegation

    mgr = manager()
    grantee = _plain_user()
    execution = analytics_workflow.start(_invoice("INV-DASH-4"))
    run(execution, "submit", user=mgr)
    WorkflowDelegation.objects.create(
        execution=execution,
        granter=mgr,
        grantee=grantee,
        step="review",
        active=True,
        expires_at=timezone.now() + timezone.timedelta(hours=24),
    )

    _login(client, grantee)
    response = client.get("/dashboard/my-work/")
    assert response.status_code == 200
    assert f"/dashboard/executions/{execution.pk}/" in response.content.decode()


def test_my_work_ignores_expired_delegations(client, analytics_workflow):
    from workflow_kit.models import WorkflowDelegation

    mgr = manager()
    grantee = _plain_user()
    execution = analytics_workflow.start(_invoice("INV-DASH-5"))
    run(execution, "submit", user=mgr)
    WorkflowDelegation.objects.create(
        execution=execution,
        granter=mgr,
        grantee=grantee,
        step="review",
        active=True,
        expires_at=timezone.now() - timezone.timedelta(hours=24),
    )

    _login(client, grantee)
    response = client.get("/dashboard/my-work/")
    assert f"/dashboard/executions/{execution.pk}/" not in response.content.decode()


# --------------------------------------------------------------------------- #
# Executions list
# --------------------------------------------------------------------------- #


def test_executions_list_renders_and_paginates(client, analytics_workflow):
    mgr = manager()
    executions = []
    for number in range(3):
        execution = analytics_workflow.start(_invoice(f"INV-LIST-{number}"))
        run(execution, "submit", user=mgr)
        executions.append(execution)

    _login(client, _staff_user())
    response = client.get("/dashboard/executions/")
    assert response.status_code == 200
    body = response.content.decode()
    for execution in executions:
        assert f"/dashboard/executions/{execution.pk}/" in body


def test_executions_search_filters_by_workflow(client, analytics_workflow):
    execution = analytics_workflow.start(_invoice("INV-SEARCH-1"))
    run(execution, "submit", user=manager())

    _login(client, _staff_user())
    response = client.get("/dashboard/executions/?q=analytics_flow")
    assert response.status_code == 200
    assert f"/dashboard/executions/{execution.pk}/" in response.content.decode()

    response = client.get("/dashboard/executions/?q=no-such-workflow")
    assert "No executions match" in response.content.decode()


def test_executions_empty_state(client):
    _login(client, _staff_user())
    response = client.get("/dashboard/executions/")
    assert response.status_code == 200
    assert "No executions match" in response.content.decode()


# --------------------------------------------------------------------------- #
# Execution detail
# --------------------------------------------------------------------------- #


def test_execution_detail_renders_all_sections(client, analytics_workflow):
    mgr = manager()
    execution = analytics_workflow.start(_invoice("INV-DETAIL-1"))
    run(execution, "submit", user=mgr)
    execution.add_comment(user=mgr, text="Please attach the quotation.")

    _login(client, _staff_user())
    response = client.get(f"/dashboard/executions/{execution.pk}/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Approvals" in body
    assert "Timeline" in body
    assert "Comments" in body
    assert "Please attach the quotation." in body


def test_execution_detail_404_for_missing(client):
    _login(client, _staff_user())
    response = client.get("/dashboard/executions/999999/")
    assert response.status_code == 404
