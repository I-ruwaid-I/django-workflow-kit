"""Tests for the read-only Django admin integration.

Admin pages must let staff inspect executions, approvals and the audit trail,
but must never allow creating or mutating records through the admin — workflow
decisions belong exclusively to the public engine API.
"""

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import Client

from tests.test_project.demo.models import Invoice


@pytest.fixture
def workflow():
    from workflow_kit import Workflow
    from workflow_kit.engine import registry

    workflow = Workflow(
        name="admin_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "review"),
            ("approve", "review", "approved"),
            ("reject", "review", "rejected"),
        ],
    )
    yield workflow
    registry.unregister("admin_flow")


@pytest.fixture
def saved_models(workflow, user):
    invoice = Invoice.objects.create(number="INV-ADMIN", vendor="Acme", amount="100.00")
    execution = workflow.start(invoice)
    execution.transition("submit", user=user)
    return {"invoice": invoice, "execution": execution}


def test_models_registered():
    from django.contrib import admin
    from workflow_kit.models import Approval, WorkflowEvent, WorkflowExecution

    assert admin.site.is_registered(WorkflowExecution)
    assert admin.site.is_registered(Approval)
    assert admin.site.is_registered(WorkflowEvent)


def test_admin_is_read_only_no_add_change_delete():
    from workflow_kit.admin import (
        ApprovalAdmin,
        WorkflowEventAdmin,
        WorkflowExecutionAdmin,
    )
    from workflow_kit.models import Approval, WorkflowEvent, WorkflowExecution

    site = AdminSite()
    approval_admin = ApprovalAdmin(Approval, site)
    execution_admin = WorkflowExecutionAdmin(WorkflowExecution, site)
    event_admin = WorkflowEventAdmin(WorkflowEvent, site)

    assert approval_admin.has_add_permission(None) is False  # type: ignore[arg-type]
    assert approval_admin.has_change_permission(None) is False  # type: ignore[arg-type]
    assert approval_admin.has_delete_permission(None) is False  # type: ignore[arg-type]
    assert execution_admin.has_add_permission(None) is False  # type: ignore[arg-type]
    assert execution_admin.has_change_permission(None) is False  # type: ignore[arg-type]
    assert event_admin.has_add_permission(None) is False  # type: ignore[arg-type]


@pytest.mark.django_db
def test_admin_changelists_load_for_staff_user(saved_models):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    staff = User.objects.create(username="staffer", is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(staff)

    for url in [
        "/admin/workflow_kit/workflowexecution/",
        "/admin/workflow_kit/approval/",
        "/admin/workflow_kit/workflowevent/",
    ]:
        response = client.get(url)
        assert response.status_code == 200, url

    # The add page must refuse permission (read-only admin).
    add_page = client.get("/admin/workflow_kit/workflowexecution/add/")
    assert add_page.status_code == 403
