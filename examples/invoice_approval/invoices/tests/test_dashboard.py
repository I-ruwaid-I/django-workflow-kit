"""Dashboard tests for the Invoice Approval demo.

The dashboard is mounted at ``/dashboard/`` and consumes the same engine and
analytics layers as the rest of the demo. Regular demo accounts are not staff,
so aggregate analytics stay gated and the overview lands on My Work.
"""

import pytest

from invoices.services import create_invoice

pytestmark = pytest.mark.django_db


def test_dashboard_requires_login(client):
    response = client.get("/dashboard/")
    assert response.status_code in (302, 403)


def test_overview_renders_notice_for_regular_user(employee_client):
    response = employee_client.get("/dashboard/")
    assert response.status_code == 200
    assert b"Workflow Overview" in response.content
    assert b"do not have permission" in response.content


def test_my_work_renders_for_regular_user(employee_client):
    response = employee_client.get("/dashboard/my-work/")
    assert response.status_code == 200
    assert b"My Work" in response.content


def test_executions_renders_for_regular_user(employee_client):
    create_invoice(number="INV-DASH", customer_name="Acme", amount="500.00")
    response = employee_client.get("/dashboard/executions/")
    assert response.status_code == 200


def test_analytics_denied_for_regular_user(employee_client):
    response = employee_client.get("/dashboard/analytics/")
    assert response.status_code == 403


def test_analytics_allowed_for_staff(client, demo_users):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    staff = User.objects.create_user(username="dash-staff", password="pw", is_staff=True)
    client.force_login(staff)
    response = client.get("/dashboard/analytics/")
    assert response.status_code == 200
