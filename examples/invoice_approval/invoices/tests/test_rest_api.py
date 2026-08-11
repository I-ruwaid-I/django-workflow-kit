"""Demo tests for the optional DRF REST API.

The Invoice Approval demo mounts the workflow API at ``/api/``. These tests
cover the six demonstrated endpoints (execution, actions, transition, history,
timeline, approvals) end to end, including authorization and error mapping.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from invoices.services import create_invoice, submit_invoice

pytestmark = pytest.mark.django_db


def _started_invoice(demo_users) -> int:
    invoice = create_invoice(number="INV-API1", customer_name="Acme", amount="500.00")
    submit_invoice(invoice, user=demo_users["employee"])
    return invoice.execution.pk


def _client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_anonymous_request_is_rejected():
    response = APIClient().get("/api/executions/")
    assert response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )


def test_list_executions(demo_users):
    execution_id = _started_invoice(demo_users)
    response = _client_for(demo_users["finance"]).get("/api/executions/")
    assert response.status_code == status.HTTP_200_OK
    assert any(item["id"] == execution_id for item in response.data["results"])


def test_get_execution_detail(demo_users):
    execution_id = _started_invoice(demo_users)
    response = _client_for(demo_users["manager"]).get(f"/api/executions/{execution_id}/")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["workflow"] == "invoice_approval"
    assert response.data["current_state"] == "manager_review"


def test_get_actions(demo_users):
    execution_id = _started_invoice(demo_users)
    response = _client_for(demo_users["manager"]).get(f"/api/executions/{execution_id}/actions/")
    assert response.status_code == status.HTTP_200_OK
    names = {item["name"] for item in response.data["actions"]}
    assert {"approve", "reject"} <= names


def test_post_transition(demo_users):
    execution_id = _started_invoice(demo_users)
    response = _client_for(demo_users["manager"]).post(
        f"/api/executions/{execution_id}/transition/",
        {"action": "approve", "reason": "Quotation attached"},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.data["current_state"] == "finance_review"


def test_transition_unauthorized(demo_users):
    execution_id = _started_invoice(demo_users)
    response = _client_for(demo_users["employee"]).post(
        f"/api/executions/{execution_id}/transition/",
        {"action": "approve"},
        format="json",
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["error"] == "permission_denied"


def test_get_history(demo_users):
    execution_id = _started_invoice(demo_users)
    response = _client_for(demo_users["manager"]).get(f"/api/executions/{execution_id}/history/")
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) >= 2
    assert response.data[0]["event"] == "workflow_started"


def test_get_timeline(demo_users):
    execution_id = _started_invoice(demo_users)
    response = _client_for(demo_users["manager"]).get(f"/api/executions/{execution_id}/timeline/")
    assert response.status_code == status.HTTP_200_OK
    labels = [item["label"] for item in response.data]
    assert "Workflow started" in labels


def test_get_approvals(demo_users):
    execution_id = _started_invoice(demo_users)
    response = _client_for(demo_users["manager"]).get(f"/api/executions/{execution_id}/approvals/")
    assert response.status_code == status.HTTP_200_OK
    assert any(item["status"] == "PENDING" for item in response.data)
