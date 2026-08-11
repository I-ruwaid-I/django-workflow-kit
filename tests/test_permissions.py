"""Phase 2 tests: users, groups, Django permissions and custom providers.

These verify that authorization is enforced consistently across
``can_transition()``, ``available_actions()`` and the actual ``transition()``
execution path, and that denied transitions never modify state.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.contrib.contenttypes.models import ContentType
from workflow_kit import (
    PermissionDeniedError,
    Transition,
    Workflow,
    WorkflowConfigurationError,
)
from workflow_kit.engine import registry
from workflow_kit.models import WorkflowExecution
from workflow_kit.permissions import PermissionContext, PermissionProvider

from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture
def perm_workflow():
    workflow = Workflow(
        name="permission_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission=["Manager"]),
            Transition("reject", "review", "rejected", permission=["Manager"]),
        ],
    )
    yield workflow
    registry.unregister("permission_flow")


@pytest.fixture
def invoice():
    return Invoice.objects.create(number="INV-P1", vendor="Acme", amount="100.00")


def _user(username: str, *groups: str, superuser: bool = False):
    User = get_user_model()
    if superuser:
        user = User.objects.create_superuser(username=username, email="x@example.com", password="x")
    else:
        user = User.objects.create_user(
            username=username,
            password="test-password-123",
        )
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


@pytest.fixture
def groups():
    manager = Group.objects.create(name="Manager")
    employee = Group.objects.create(name="Employee")
    return {"manager": manager, "employee": employee}


# -- Transition permission spec validation ------------------------------------


def test_invalid_permission_spec_raises():
    with pytest.raises(WorkflowConfigurationError):
        Transition("approve", "draft", "approved", permission=123)


def test_empty_permission_list_raises():
    with pytest.raises(WorkflowConfigurationError):
        Transition("approve", "draft", "approved", permission=[])


# -- Unprotected transitions -------------------------------------------------


def test_unprotected_transition_allows_anonymous(perm_workflow, invoice):
    execution = perm_workflow.start(invoice)
    perm_workflow.transition(execution, "submit", user=AnonymousUser())
    assert execution.current_state == "review"


def test_unprotected_transition_needs_no_user(perm_workflow, invoice):
    execution = perm_workflow.start(invoice)
    perm_workflow.transition(execution, "submit")
    assert execution.current_state == "review"


# -- Group-based authorization -----------------------------------------------


def test_authorized_group_user_can_approve(groups, perm_workflow, invoice):
    execution = perm_workflow.start(invoice)
    perm_workflow.transition(execution, "submit")
    manager = _user("mgr", "Manager")
    perm_workflow.transition(execution, "approve", user=manager)
    assert execution.current_state == "approved"


def test_unauthorized_group_user_denied(groups, perm_workflow, invoice):
    execution = perm_workflow.start(invoice)
    perm_workflow.transition(execution, "submit")
    employee = _user("emp", "Employee")
    expected = "User is not authorized to execute transition 'approve'."
    with pytest.raises(PermissionDeniedError, match=expected):
        perm_workflow.transition(execution, "approve", user=employee)
    assert execution.current_state == "review"


def test_single_group_string_requirement(groups, invoice):
    workflow = Workflow(
        name="single_group_flow",
        initial="draft",
        states=["draft", "approved"],
        transitions=[Transition("sign", "draft", "approved", permission="Manager")],
    )
    execution = workflow.start(invoice)
    manager = get_user_model().objects.create_user("single-mgr", password="x")
    manager.groups.add(Group.objects.get(name="Manager"))
    workflow.transition(execution, "sign", user=manager)
    assert execution.current_state == "approved"
    registry.unregister("single_group_flow")


def test_group_membership_changes_are_reevaluated(groups, perm_workflow, invoice):
    execution = perm_workflow.start(invoice)
    perm_workflow.transition(execution, "submit")
    manager = _user("mgr-v2", "Manager")
    assert perm_workflow.can_transition(execution, "approve", manager) is True
    manager.groups.clear()
    with pytest.raises(PermissionDeniedError):
        perm_workflow.transition(execution, "approve", user=manager)
    assert execution.current_state == "review"


# -- Anonymous and missing users ---------------------------------------------


def test_anonymous_denied_for_protected(perm_workflow, invoice):
    execution = perm_workflow.start(invoice)
    perm_workflow.transition(execution, "submit")
    with pytest.raises(PermissionDeniedError):
        perm_workflow.transition(execution, "approve", user=AnonymousUser())
    assert execution.current_state == "review"


def test_missing_user_denied_for_protected(perm_workflow, invoice):
    execution = perm_workflow.start(invoice)
    perm_workflow.transition(execution, "submit")
    with pytest.raises(PermissionDeniedError):
        perm_workflow.transition(execution, "approve")
    assert execution.current_state == "review"


# -- Superusers --------------------------------------------------------------


def test_superuser_bypasses_authorization(perm_workflow, invoice):
    execution = perm_workflow.start(invoice)
    perm_workflow.transition(execution, "submit")
    boss = _user("boss", superuser=True)
    perm_workflow.transition(execution, "approve", user=boss)
    assert execution.current_state == "approved"


# -- Django permissions ------------------------------------------------------


def _sign_permission():
    content_type = ContentType.objects.get_for_model(Invoice)
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename="can_sign_invoice",
        defaults={"name": "Can sign invoice"},
    )
    return permission


def test_django_permission_requirement(invoice):
    permission = _sign_permission()
    label = permission.content_type.app_label
    workflow = Workflow(
        name="django_perm_flow",
        initial="draft",
        states=["draft", "approved"],
        transitions=[
            Transition(
                "sign",
                "draft",
                "approved",
                permission=f"{label}.can_sign_invoice",
            )
        ],
    )
    allowed = get_user_model().objects.create_user("allowed", password="x")
    allowed.user_permissions.add(permission)
    denied = get_user_model().objects.create_user("denied", password="x")

    execution = workflow.start(invoice)
    workflow.transition(execution, "sign", user=allowed)
    assert execution.current_state == "approved"

    second = Invoice.objects.create(number="INV-P2", vendor="Globex", amount="1.00")
    execution2 = workflow.start(second)
    with pytest.raises(PermissionDeniedError):
        workflow.transition(execution2, "sign", user=denied)
    assert execution2.current_state == "draft"
    registry.unregister("django_perm_flow")


def test_multiple_requirements_all_must_pass(invoice):
    permission = _sign_permission()
    label = permission.content_type.app_label
    workflow = Workflow(
        name="multi_rule_flow",
        initial="draft",
        states=["draft", "approved"],
        transitions=[
            Transition(
                "sign",
                "draft",
                "approved",
                permission=["Manager", f"{label}.can_sign_invoice"],
            )
        ],
    )
    group = Group.objects.create(name="Manager")
    user = get_user_model().objects.create_user("multi-allowed", password="x")
    user.groups.add(group)
    user.user_permissions.add(permission)

    execution = workflow.start(invoice)
    workflow.transition(execution, "sign", user=user)
    assert execution.current_state == "approved"

    group_only = get_user_model().objects.create_user("multi-group", password="x")
    group_only.groups.add(group)
    second = Invoice.objects.create(number="INV-P3", vendor="Globex", amount="1.00")
    execution2 = workflow.start(second)
    with pytest.raises(PermissionDeniedError):
        workflow.transition(execution2, "sign", user=group_only)
    assert execution2.current_state == "draft"
    registry.unregister("multi_rule_flow")


# -- Custom providers and callables ------------------------------------------


def test_custom_provider_allows_and_denies(invoice):
    class AmountLimitProvider(PermissionProvider):
        def __init__(self, limit):
            self.limit = limit

        def can_execute(self, context: PermissionContext) -> bool:
            return context.object.amount <= self.limit

    workflow = Workflow(
        name="provider_flow",
        initial="draft",
        states=["draft", "approved"],
        transitions=[
            Transition("sign", "draft", "approved", permission=AmountLimitProvider(Decimal("500")))
        ],
    )
    user = get_user_model().objects.create_user("provider-user", password="x")

    small = Invoice.objects.create(number="INV-SMALL", vendor="A", amount="100.00")
    execution = workflow.start(small)
    workflow.transition(execution, "sign", user=user)
    assert execution.current_state == "approved"

    big = Invoice.objects.create(number="INV-BIG", vendor="B", amount="5000.00")
    execution2 = workflow.start(big)
    with pytest.raises(PermissionDeniedError):
        workflow.transition(execution2, "sign", user=user)
    assert execution2.current_state == "draft"
    registry.unregister("provider_flow")


def test_callable_permission(invoice):
    def only_jane(context):
        return context.user.username == "jane"

    workflow = Workflow(
        name="callable_flow",
        initial="draft",
        states=["draft", "approved"],
        transitions=[Transition("sign", "draft", "approved", permission=only_jane)],
    )
    jane = get_user_model().objects.create_user("jane", password="x")
    bob = get_user_model().objects.create_user("bob", password="x")

    execution = workflow.start(invoice)
    workflow.transition(execution, "sign", user=jane)
    assert execution.current_state == "approved"

    second = Invoice.objects.create(number="INV-CALL", vendor="C", amount="1.00")
    execution2 = workflow.start(second)
    with pytest.raises(PermissionDeniedError):
        workflow.transition(execution2, "sign", user=bob)
    assert execution2.current_state == "draft"
    registry.unregister("callable_flow")


def test_provider_receives_controlled_context(perm_workflow, invoice):
    captured: dict = {}

    class ProbeProvider(PermissionProvider):
        def can_execute(self, context: PermissionContext) -> bool:
            captured.update(
                user=context.user,
                execution=context.execution,
                transition=context.transition,
                workflow=context.workflow,
                object=context.object,
            )
            return True

    probe_workflow = Workflow(
        name="probe_flow",
        initial="draft",
        states=["draft", "approved"],
        transitions=[Transition("go", "draft", "approved", permission=ProbeProvider())],
    )
    manager = _user("probe-mgr", "Manager")
    execution = probe_workflow.start(invoice)
    probe_workflow.transition(execution, "go", user=manager)

    assert captured["user"] is manager
    assert captured["execution"].pk == execution.pk
    assert captured["workflow"] is probe_workflow
    assert captured["object"] == invoice
    assert isinstance(captured["transition"], Transition)
    assert captured["transition"].name == "go"
    registry.unregister("probe_flow")


# -- can_transition / available_actions --------------------------------------


def test_can_transition_respects_authorization(groups, perm_workflow, invoice):
    execution = perm_workflow.start(invoice)
    manager = _user("mgr-can", "Manager")
    employee = _user("emp-can", "Employee")
    perm_workflow.transition(execution, "submit")

    assert perm_workflow.can_transition(execution, "approve", manager) is True
    assert perm_workflow.can_transition(execution, "approve", employee) is False
    assert perm_workflow.can_transition(execution, "approve", AnonymousUser()) is False
    assert perm_workflow.can_transition(execution, "approve") is False
    assert perm_workflow.can_transition(execution, "submit", manager) is False


def test_available_actions_filters_by_user(groups, perm_workflow, invoice):
    execution = perm_workflow.start(invoice)
    manager = _user("mgr-avail", "Manager")
    employee = _user("emp-avail", "Employee")

    assert perm_workflow.available_actions(execution, employee) == ["submit"]
    perm_workflow.transition(execution, "submit")
    assert perm_workflow.available_actions(execution, employee) == []
    assert perm_workflow.available_actions(execution, AnonymousUser()) == []
    assert set(perm_workflow.available_actions(execution, manager)) == {"approve", "reject"}
    assert perm_workflow.available_actions(execution) == []


# -- Enforcement and state integrity -----------------------------------------


def test_denied_transition_does_not_write(perm_workflow, invoice):
    execution = perm_workflow.start(invoice)
    perm_workflow.transition(execution, "submit")
    employee = _user("emp-write", "Employee")
    with (
        patch("workflow_kit.models.execution.WorkflowExecution.save") as mocked,
        pytest.raises(PermissionDeniedError),
    ):
        perm_workflow.transition(execution, "approve", user=employee)
    mocked.assert_not_called()
    fresh = WorkflowExecution.objects.get(pk=execution.pk)
    assert fresh.current_state == "review"


def test_denied_transition_leaves_state_unchanged(groups, perm_workflow, invoice):
    execution = perm_workflow.start(invoice)
    perm_workflow.transition(execution, "submit")
    employee = _user("emp-state", "Employee")
    with pytest.raises(PermissionDeniedError):
        perm_workflow.transition(execution, "approve", user=employee)
    assert execution.current_state == "review"
    fresh = WorkflowExecution.objects.get(pk=execution.pk)
    assert fresh.current_state == "review"


def test_authorization_enforced_during_transition(perm_workflow, invoice):
    execution = perm_workflow.start(invoice)
    perm_workflow.transition(execution, "submit")
    employee = _user("emp-enf", "Employee")
    with pytest.raises(PermissionDeniedError):
        perm_workflow.transition(execution, "approve", user=employee)
    assert execution.current_state == "review"


def test_only_authorized_user_advances_conflict(groups, perm_workflow, invoice):
    # Simulates simultaneous actions: the unauthorized attempt is denied while
    # the authorized one succeeds; the final state is consistent.
    execution = perm_workflow.start(invoice)
    perm_workflow.transition(execution, "submit")
    employee = _user("emp-conf", "Employee")
    manager = _user("mgr-conf", "Manager")

    with pytest.raises(PermissionDeniedError):
        perm_workflow.transition(execution, "approve", user=employee)
    perm_workflow.transition(execution, "approve", user=manager)

    assert execution.current_state == "approved"
    assert WorkflowExecution.objects.get(pk=execution.pk).current_state == "approved"
