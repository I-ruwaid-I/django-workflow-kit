"""Phase 6 tests: the optional DRF REST API.

The API is a thin HTTP layer over the workflow engine. These tests verify
authentication, authorization, actions, transitions, filtering/pagination and
the history / timeline / approvals endpoints, plus the security guarantees that
internal details never leak through HTTP.
"""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from workflow_kit import Transition, Workflow
from workflow_kit.conditions import GreaterThan
from workflow_kit.engine import registry
from workflow_kit.exceptions import WorkflowNotFoundError
from workflow_kit.models import WorkflowExecution

from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


# -- fixtures -----------------------------------------------------------------


@pytest.fixture
def api_workflow():
    workflow = Workflow(
        name="api_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission=["Manager"]),
            Transition("reject", "review", "rejected", permission=["Manager"]),
        ],
    )
    yield workflow
    registry.unregister("api_flow")


@pytest.fixture
def conditional_workflow():
    workflow = Workflow(
        name="api_conditional_flow",
        initial="review",
        states=["review", "approved", "rejected", "pending_finance"],
        transitions=[
            Transition("approve", "review", "approved", permission=["Manager"]),
            Transition(
                "esc",
                "review",
                "pending_finance",
                permission=["Manager"],
                conditions=[GreaterThan("amount", 10000)],
            ),
        ],
    )
    yield workflow
    registry.unregister("api_conditional_flow")


@pytest.fixture
def invoice():
    return Invoice.objects.create(number="INV-API1", vendor="Acme", amount="100.00")


@pytest.fixture
def execution(api_workflow, invoice) -> WorkflowExecution:
    return api_workflow.start(invoice)


def _user(username: str, *groups: str):
    from django.contrib.auth import get_user_model as gum
    from django.contrib.auth.models import Group

    user, _ = gum().objects.get_or_create(
        username=username,
        defaults={"password": "test-password-123"},
    )
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


def _client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def _manager():
    return _user("mgr", "Manager")


def _finance():
    return _user("fin", "Finance")


def _employee():
    return _user("emp", "Employee")


# -- authentication ------------------------------------------------------------


def test_anonymous_requests_are_denied():
    client = APIClient()
    response = client.get("/api/executions/")
    assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


def test_authenticated_user_can_list(execution, invoice):
    response = _client_for(_manager()).get("/api/executions/")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    item = response.data["results"][0]
    assert item["id"] == execution.pk
    assert item["workflow"] == "api_flow"
    assert item["current_state"] == "draft"
    assert item["object"] == {"type": "demo.invoice", "id": invoice.pk}


# -- list / detail -------------------------------------------------------------


def test_execution_detail_includes_available_actions(execution):
    manager = _manager()
    client = _client_for(manager)
    response = client.get(f"/api/executions/{execution.pk}/")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["available_actions"] == [{"name": "submit", "label": "Submit"}]


def test_execution_detail_not_found():
    response = _client_for(_manager()).get("/api/executions/99999/")
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_list_filter_by_workflow(execution):
    other = api_workflow_execution(workflow_name="api_flow_other", number="INV-OTHER")
    response = _client_for(_manager()).get("/api/executions/?workflow=api_flow")
    assert response.status_code == status.HTTP_200_OK
    ids = [item["id"] for item in response.data["results"]]
    assert execution.pk in ids
    assert other.pk not in ids


def test_list_filter_by_state(execution):
    response = _client_for(_manager()).get("/api/executions/?current_state=draft")
    assert response.status_code == status.HTTP_200_OK
    assert [item["id"] for item in response.data["results"]] == [execution.pk]


def test_list_filter_by_completed(execution, api_workflow):
    execution.transition("submit")
    execution = WorkflowExecution.objects.get(pk=execution.pk)
    response = _client_for(_manager()).get("/api/executions/?completed=false")
    assert [item["id"] for item in response.data["results"]] == [execution.pk]


def test_list_pagination(execution):
    for i in range(25):
        api_workflow_execution(number=f"INV-PG{i}")
    response = _client_for(_manager()).get("/api/executions/?page_size=5")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 26
    assert len(response.data["results"]) == 5


# -- actions -------------------------------------------------------------------


def test_actions_reflect_user_permissions(execution):
    response = _client_for(_manager()).get(f"/api/executions/{execution.pk}/actions/")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["actions"] == [{"name": "submit", "label": "Submit"}]

    execution.transition("submit")
    response = _client_for(_manager()).get(f"/api/executions/{execution.pk}/actions/")
    assert response.status_code == status.HTTP_200_OK
    assert {a["name"] for a in response.data["actions"]} == {"approve", "reject"}
    assert {a["label"] for a in response.data["actions"]} == {"Approve", "Reject"}


def test_actions_exclude_unauthorized_user(execution, api_workflow):
    api_workflow.transition(execution, "submit")
    response = _client_for(_employee()).get(f"/api/executions/{execution.pk}/actions/")
    assert response.data["actions"] == []


def test_actions_exclude_condition_failed(conditional_workflow):
    invoice = Invoice.objects.create(number="INV-SMALL", vendor="Acme", amount="5000.00")
    execution = conditional_workflow.start(invoice)
    response = _client_for(_manager()).get(f"/api/executions/{execution.pk}/actions/")
    # The amount-conditioned 'esc' action is hidden because the condition fails;
    # the unconditional 'approve' remains available.
    assert response.data["actions"] == [{"name": "approve", "label": "Approve"}]


# -- transition ----------------------------------------------------------------


def test_transition_success(execution, api_workflow):
    client = _client_for(_employee())
    response = client.post(
        f"/api/executions/{execution.pk}/transition/",
        {"action": "submit"},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    body = response.data
    assert body["id"] == execution.pk
    assert body["action"] == "submit"
    assert body["previous_state"] == "draft"
    assert body["current_state"] == "review"
    assert body["is_completed"] is False
    assert WorkflowExecution.objects.get(pk=execution.pk).current_state == "review"


def test_transition_invalid(execution, api_workflow):
    response = _client_for(_manager()).post(
        f"/api/executions/{execution.pk}/transition/",
        {"action": "approve"},
        format="json",
    )
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["error"] == "invalid_transition"
    assert "message" in response.data


def test_transition_permission_denied(execution, api_workflow):
    api_workflow.transition(execution, "submit")
    response = _client_for(_employee()).post(
        f"/api/executions/{execution.pk}/transition/",
        {"action": "approve"},
        format="json",
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["error"] == "permission_denied"


def test_transition_condition_failed(conditional_workflow):
    invoice = Invoice.objects.create(number="INV-COND", vendor="Acme", amount="1.00")
    execution = conditional_workflow.start(invoice)
    # 'esc' requires amount > 10000; the small invoice fails that condition.
    response = _client_for(_manager()).post(
        f"/api/executions/{execution.pk}/transition/",
        {"action": "esc"},
        format="json",
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.data["error"] == "condition_failed"


def test_transition_completed_workflow(execution, api_workflow):
    api_workflow.transition(execution, "submit")
    manager = _manager()
    api_workflow.transition(execution, "approve", user=manager)
    response = _client_for(manager).post(
        f"/api/executions/{execution.pk}/transition/",
        {"action": "approve"},
        format="json",
    )
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["error"] == "workflow_completed"
    assert response.data["message"].startswith("Workflow 'api_flow' is already completed")


def test_transition_missing_action(execution):
    response = _client_for(_manager()).post(
        f"/api/executions/{execution.pk}/transition/",
        {},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_transition_reason_is_accepted(execution, api_workflow):
    manager = _manager()
    client = _client_for(manager)
    api_workflow.transition(execution, "submit")
    response = client.post(
        f"/api/executions/{execution.pk}/transition/",
        {"action": "approve", "reason": "Looks fine"},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.data["current_state"] == "approved"


def test_transition_hidden_action_cannot_be_executed(execution, api_workflow):
    """A user may not execute an action that authorization hides."""
    api_workflow.transition(execution, "submit")
    response = _client_for(_employee()).post(
        f"/api/executions/{execution.pk}/transition/",
        {"action": "approve"},
        format="json",
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


# -- history / timeline / approvals -------------------------------------------


def test_history_returns_structured_audit(execution, api_workflow):
    api_workflow.transition(execution, "submit")
    response = _client_for(_manager()).get(f"/api/executions/{execution.pk}/history/")
    assert response.status_code == status.HTTP_200_OK
    events = response.data
    assert len(events) >= 2
    first = events[0]
    assert first["event"] == "workflow_started"
    assert first["target_state"] == "draft"
    assert "timestamp" in first


def test_timeline_endpoint_returns_structured_timeline(execution, api_workflow):
    api_workflow.transition(execution, "submit")
    response = _client_for(_manager()).get(f"/api/executions/{execution.pk}/timeline/")
    assert response.status_code == status.HTTP_200_OK
    labels = [item["label"] for item in response.data]
    assert "Workflow started" in labels
    assert "State changed" in labels


def test_approvals_endpoint(execution, api_workflow):
    api_workflow.transition(execution, "submit")
    response = _client_for(_manager()).get(f"/api/executions/{execution.pk}/approvals/")
    assert response.status_code == status.HTTP_200_OK
    approvals = response.data
    assert len(approvals) == 1
    assert approvals[0]["step"] == "review"
    assert approvals[0]["status"] == "PENDING"
    assert approvals[0]["mode"] == "ALL"
    assert "assignment" in approvals[0]
    assert "is_overdue" in approvals[0]


def test_delegate_endpoint_forwards_approval(execution, api_workflow):
    from workflow_kit.approvals.requirements import ApprovalRequirement

    api_workflow._approval_requirements["review"] = ApprovalRequirement(approvers=["Manager"])
    api_workflow.transition(execution, "submit")
    proxy = _user("api_proxy")
    response = _client_for(_manager()).post(
        f"/api/executions/{execution.pk}/delegate/",
        {"grantee": "api_proxy"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["grantee"] == "api_proxy"

    decided = execution.approve(proxy, reason="proxy vote")
    assert decided.status == "APPROVED"
    assert decided.delegation is not None


def test_escalate_endpoint(execution, api_workflow):
    api_workflow.transition(execution, "submit")
    response = _client_for(_manager()).post(
        f"/api/executions/{execution.pk}/escalate/",
        {"approver": "Executive", "reason": "urgent"},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.data["mode"] == "ANY"

    from workflow_kit.models import Approval

    escalated = Approval.objects.get(pk=response.data["id"])
    assert escalated.assignment["name"] == "Executive"
    assert escalated.assignment["escalated"] is True


def test_escalate_endpoint_unknown_approver_fails(execution, api_workflow):
    api_workflow.transition(execution, "submit")
    response = _client_for(_manager()).post(
        f"/api/executions/{execution.pk}/escalate/",
        {"approver": ""},
        format="json",
    )
    assert response.status_code in (
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


# -- security -----------------------------------------------------------------


def test_arbitrary_object_fields_are_not_leaked(execution):
    response = _client_for(_manager()).get(f"/api/executions/{execution.pk}/")
    assert "object" not in response.data or set(response.data["object"]) == {"type", "id"}
    assert "vendor" not in response.data
    assert "amount" not in response.data


def test_python_stacktrace_is_not_exposed_on_error(execution, api_workflow):
    response = _client_for(_employee()).post(
        f"/api/executions/{execution.pk}/transition/",
        {"action": "approve"},
        format="json",
    )
    content = response.content.decode()
    assert "Traceback" not in content
    assert 'File "' not in content
    assert "exception" not in content


# -- helpers ------------------------------------------------------------------


def api_workflow_execution(
    workflow_name: str = "api_flow",
    number: str = "INV-OTHER",
) -> WorkflowExecution:
    invoice = Invoice.objects.create(number=number, vendor="Globex", amount="50.00")
    try:
        wf = registry.get_workflow(workflow_name)
    except WorkflowNotFoundError:
        wf = Workflow(
            name=workflow_name,
            initial="draft",
            states=["draft", "review", "approved", "rejected"],
            transitions=[
                ("submit", "draft", "review"),
                Transition("approve", "review", "approved", permission=["Manager"]),
                Transition("reject", "review", "rejected", permission=["Manager"]),
            ],
        )
    return wf.start(invoice)
