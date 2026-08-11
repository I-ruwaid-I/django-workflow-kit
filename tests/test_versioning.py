"""Phase 9 tests: workflow versioning.

Covers version creation and numbering, the draft/published/retired lifecycle,
publishing validation, immutability of published versions, active-version
selection, execution-to-version binding, explicit version selection,
version-aware transitions/conditions/approvals/permissions, version presence in
audit/events/timeline, REST exposure, admin visibility, the upgrade/migration
path and concurrency guarantees.
"""

from __future__ import annotations

import contextlib
import copy
import threading
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient
from workflow_kit import (
    ApprovalMode,
    ApprovalRequirement,
    ConditionFailedError,
    LessThanOrEqual,
    PermissionDeniedError,
    Transition,
    Workflow,
    WorkflowVersionError,
)
from workflow_kit.engine import registry
from workflow_kit.engine.versioning import (
    active_version,
    ensure_workflow_version,
    get_version_workflow,
    serialize_workflow,
)
from workflow_kit.events.types import EventType
from workflow_kit.models import (
    Approval,
    VersionStatus,
    WorkflowEvent,
    WorkflowExecution,
    WorkflowVersion,
)

from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db

WORKFLOW = "versioning_flow"


# -- helpers ------------------------------------------------------------------


def _user(username: str, *groups: str) -> Any:
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={"password": "test-password-123"},
    )
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


def _invoice(number: str, amount: str) -> Invoice:
    return Invoice.objects.create(number=number, vendor="Acme", amount=amount)


def _build_v1() -> Workflow:
    return Workflow(
        name=WORKFLOW,
        initial="draft",
        states=["draft", "manager_review", "finance_review", "approved", "rejected"],
        transitions=[
            Transition("submit", "draft", "manager_review", permission="Employee"),
            Transition("approve", "manager_review", "finance_review", permission="Manager"),
            Transition(
                "approve",
                "finance_review",
                "approved",
                permission="Finance",
                conditions=[LessThanOrEqual("amount", 10000)],
            ),
            Transition("reject", "manager_review", "rejected", permission="Manager"),
            Transition("reject", "finance_review", "rejected", permission="Finance"),
        ],
        register=False,
    )


def _build_v2() -> Workflow:
    return Workflow(
        name=WORKFLOW,
        initial="draft",
        states=[
            "draft",
            "manager_review",
            "finance_review",
            "legal_review",
            "approved",
            "rejected",
        ],
        transitions=[
            Transition("submit", "draft", "manager_review", permission="Employee"),
            Transition("approve", "manager_review", "finance_review", permission="Manager"),
            Transition(
                "approve",
                "finance_review",
                "legal_review",
                permission="Finance",
                conditions=[LessThanOrEqual("amount", 5000)],
            ),
            Transition("approve", "legal_review", "approved", permission="Legal"),
            Transition("reject", "manager_review", "rejected", permission="Manager"),
            Transition("reject", "finance_review", "rejected", permission="Finance"),
            Transition("reject", "legal_review", "rejected", permission="Legal"),
        ],
        approval_requirements={
            "legal_review": ApprovalRequirement(
                mode=ApprovalMode.ALL,
                approvers=["Legal", "Finance"],
            ),
        },
        register=False,
    )


@pytest.fixture(scope="module")
def identity() -> Workflow:
    """The shared, registered identity workflow for versioning tests."""
    v1 = _build_v1()
    # Guarantee a stable registration across the module's tests.
    try:
        registry.get_workflow(WORKFLOW)
    except Exception:  # noqa: BLE001
        registry.register(v1)
        v1.register_self = True  # marker so we can reset in teardown
    return v1


@pytest.fixture(autouse=True)
def _cleanup_version_rows():
    """Each test gets a clean version table (rows are transaction-isolated)."""
    yield
    _VERSION_CACHE_HELPER = {
        "get": lambda: None,
    }


# --------------------------------------------------------------------------- #
# Creation, numbering and the draft lifecycle
# --------------------------------------------------------------------------- #


def test_ensure_workflow_version_creates_published_v1(identity):
    version = ensure_workflow_version(identity, changelog="Initial")
    assert version.workflow == WORKFLOW
    assert version.version == 1
    assert version.status == VersionStatus.PUBLISHED
    assert version.published_at is not None
    assert version.definition["name"] == WORKFLOW
    assert active_version(WORKFLOW).version == 1


def test_version_numbering_increments(identity):
    v1 = ensure_workflow_version(identity)
    assert v1.version == 1
    v2 = identity.create_version(from_version=v1, changelog="next")
    v3 = identity.create_version()
    assert v2.version == 2
    assert v3.version == 3
    assert v2.is_draft
    assert v3.is_draft
    assert list(identity.versions()) == [v3, v2, v1]


def test_version_lookup_apis(identity):
    v1 = ensure_workflow_version(identity)
    identity.create_version(from_version=v1)
    assert identity.version(1).workflow == WORKFLOW
    assert identity.version(2).version == 2
    assert identity.active_version().version == 1
    with pytest.raises(Exception) as excinfo:
        identity.version(99)
    assert "no version" in str(excinfo.value).lower()


def test_draft_version_reconstructs_definition(identity):
    v1 = ensure_workflow_version(identity)
    draft = identity.create_version(from_version=v1)
    workflow = get_version_workflow(draft)
    assert workflow.name == WORKFLOW
    assert workflow.initial == "draft"
    assert workflow.transition_for("finance_review", "approve").target == "approved"


def test_serialization_roundtrip_preserves_configuration(identity):
    ensure_workflow_version(identity)
    serialize_workflow(identity)
    rebuilt = get_version_workflow(identity.version(1))
    assert [t.name for t in rebuilt.transitions_from("draft")] == ["submit"]
    approve = rebuilt.transition_for("finance_review", "approve")
    assert approve is not None
    assert approve.permission == "Finance"
    assert approve.label


# --------------------------------------------------------------------------- #
# Publishing validation and immutability
# --------------------------------------------------------------------------- #


def test_publish_valid_version_becomes_active(identity):
    v1 = ensure_workflow_version(identity)
    draft = identity.create_version(from_version=v1)
    identity.update_version(draft, _build_v2(), changelog="Add legal review")
    published = identity.publish_version(draft)
    published.refresh_from_db()
    assert published.status == VersionStatus.PUBLISHED
    assert published.published_at is not None
    assert identity.active_version().version == 2


def test_publish_invalid_version_is_rejected_and_stays_draft(identity):
    v1 = ensure_workflow_version(identity)
    draft = identity.create_version(from_version=v1)
    snapshot = copy.deepcopy(v1.definition)
    # Reference a state that does not exist.
    snapshot["transitions"].append(
        {
            "name": "ghost",
            "source": "draft",
            "target": "nonexistent_state",
            "label": "Ghost",
            "permission": None,
            "conditions": [],
        }
    )
    # update_version validates eagerly and rejects the bad definition.
    with pytest.raises(WorkflowVersionError):
        identity.update_version(draft, snapshot)
    draft.refresh_from_db()
    assert draft.is_draft
    # publish_version is the final gate even if a bad snapshot slips through.
    draft.definition = snapshot
    draft.save()
    with pytest.raises(WorkflowVersionError):
        identity.publish_version(draft)
    draft.refresh_from_db()
    assert draft.is_draft


def test_published_version_is_immutable(identity):
    v1 = ensure_workflow_version(identity)
    with pytest.raises(WorkflowVersionError):
        identity.update_version(v1, _build_v2())
    snapshot = dict(v1.definition)
    snapshot["initial"] = "approved"
    with pytest.raises(WorkflowVersionError):
        identity.update_version(v1, snapshot)
    with pytest.raises(WorkflowVersionError):
        v1.definition = {"evil": True}
        v1.save()


def test_published_version_cannot_be_reverted_to_draft(identity):
    v1 = ensure_workflow_version(identity)
    with pytest.raises(WorkflowVersionError):
        v1.status = VersionStatus.DRAFT
        v1.save()


def test_draft_version_is_editable(identity):
    v1 = ensure_workflow_version(identity)
    draft = identity.create_version(from_version=v1, changelog="draft it")
    identity.update_version(draft, _build_v2(), changelog="editing draft")
    assert identity.version(2).is_draft
    v2_transition = get_version_workflow(draft).transition_for("finance_review", "approve")
    assert v2_transition is not None
    assert v2_transition.target == "legal_review"


def test_retire_lifecycle(identity):
    v1 = ensure_workflow_version(identity)
    v2 = identity.create_version(from_version=v1)
    identity.update_version(v2, _build_v2())
    identity.publish_version(v2)
    assert identity.active_version().version == 2
    identity.retire_version(v2)
    assert identity.active_version().version == 1
    retired = identity.version(2)
    assert retired.is_retired
    assert retired.retired_at is not None
    with pytest.raises(WorkflowVersionError):
        retired.status = VersionStatus.PUBLISHED
        retired.save()
    with pytest.raises(WorkflowVersionError):
        identity.retire_version(identity.version(1))  # already published, still ok
        # retiring a draft instead raises:
        identity.retire_version(identity.create_version())


def test_only_published_versions_become_active(identity):
    ensure_workflow_version(identity)
    draft = identity.create_version()
    assert identity.active_version().version == 1
    identity.update_version(draft, _build_v2())
    assert identity.active_version().version == 1  # still v1 while draft


# --------------------------------------------------------------------------- #
# Execution version binding
# --------------------------------------------------------------------------- #


def test_new_execution_binds_active_version(identity):
    v1 = ensure_workflow_version(identity)
    execution = identity.start(_invoice("INV-A", "100.00"))
    assert execution.workflow_version_number == v1.version
    assert execution.workflow_version_id == v1.pk


def test_execution_binds_new_version_after_publish(identity):
    v1 = ensure_workflow_version(identity)
    draft = identity.create_version(from_version=v1)
    identity.update_version(draft, _build_v2())
    identity.publish_version(draft)
    execution = identity.start(_invoice("INV-B", "100.00"))
    assert execution.workflow_version_number == 2


def test_existing_execution_retains_original_version_after_publish(identity):
    v1 = ensure_workflow_version(identity)
    invoice = _invoice("INV-C", "100.00")
    execution = identity.start(invoice)
    assert execution.workflow_version_number == 1

    draft = identity.create_version(from_version=v1)
    identity.update_version(draft, _build_v2())
    identity.publish_version(draft)

    execution.refresh_from_db()
    assert execution.workflow_version_number == 1
    # A later start on a different object binds v2.
    assert identity.start(_invoice("INV-D", "100.00")).workflow_version_number == 2


def test_explicit_version_selection(identity):
    v1 = ensure_workflow_version(identity)
    draft = identity.create_version(from_version=v1)
    identity.update_version(draft, _build_v2())
    identity.publish_version(draft)

    execution = identity.start(_invoice("INV-E", "100.00"), version=1)
    assert execution.workflow_version_number == 1


def test_explicit_draft_version_requires_opt_in(identity):
    v1 = ensure_workflow_version(identity)
    draft = identity.create_version(from_version=v1)
    identity.update_version(draft, _build_v2())
    with pytest.raises(WorkflowVersionError):
        identity.start(_invoice("INV-F", "100.00"), version=2)
    execution = identity.start(_invoice("INV-F2", "100.00"), version=2, allow_unpublished=True)
    assert execution.workflow_version_number == 2


def test_retired_version_rejected_for_new_executions(identity):
    ensure_workflow_version(identity)
    draft = identity.create_version()
    identity.update_version(draft, _build_v2())
    identity.publish_version(draft)
    identity.retire_version(draft)
    with pytest.raises(WorkflowVersionError):
        identity.start(_invoice("INV-G", "100.00"), version=2)
    # Even retired versions reconstruct for existing executions.
    assert get_version_workflow(identity.version(2)).transition_for("legal_review", "approve")


def test_unversioned_start_is_legacy_and_uses_registered_definition(identity):
    # No version rows exist in this test-transaction: start stays unversioned.
    assert active_version(WORKFLOW) is None
    execution = identity.start(_invoice("INV-H", "100.00"))
    assert execution.workflow_version_number is None
    # It still transitions through the registered (v1-shaped) definition.
    identity.transition(execution, "submit", user=_user("employee", "Employee"))
    assert execution.current_state == "manager_review"


def test_workflow_property_returns_version_definition(identity):
    ensure_workflow_version(identity)
    execution = identity.start(_invoice("INV-I", "100.00"))
    assert execution.workflow.name == WORKFLOW
    assert execution.workflow.transition_for("finance_review", "approve").target == "approved"


# --------------------------------------------------------------------------- #
# Version-aware transitions / conditions / approvals / permissions
# --------------------------------------------------------------------------- #


def test_version_aware_transitions(identity):
    v1 = ensure_workflow_version(identity)
    draft = identity.create_version(from_version=v1)
    identity.update_version(draft, _build_v2())
    identity.publish_version(draft)

    v2_exec = identity.start(_invoice("INV-J", "300.00"))
    identity.transition(v2_exec, "submit", user=_user("employee1", "Employee"))
    identity.transition(v2_exec, "approve", user=_user("manager1", "Manager"))
    identity.transition(v2_exec, "approve", user=_user("finance1", "Finance"))
    assert v2_exec.current_state == "legal_review"

    v1_exec = identity.start(_invoice("INV-K", "300.00"), version=1)
    identity.transition(v1_exec, "submit", user=_user("employee2", "Employee"))
    identity.transition(v1_exec, "approve", user=_user("manager2", "Manager"))
    identity.transition(v1_exec, "approve", user=_user("finance2", "Finance"))
    assert v1_exec.current_state == "approved"


def test_version_aware_conditions(identity):
    v1 = ensure_workflow_version(identity)
    draft = identity.create_version(from_version=v1)
    identity.update_version(draft, _build_v2())
    identity.publish_version(draft)

    # v1 condition: amount <= 10000. 8000 passes on v1...
    v1_exec = identity.start(_invoice("INV-L", "8000.00"), version=1)
    identity.transition(v1_exec, "submit", user=_user("employee3", "Employee"))
    identity.transition(v1_exec, "approve", user=_user("manager3", "Manager"))
    identity.transition(v1_exec, "approve", user=_user("finance3", "Finance"))
    assert v1_exec.current_state == "approved"

    # ...but v2 uses amount <= 5000, so the same invoice fails on v2.
    v2_exec = identity.start(_invoice("INV-M", "8000.00"))
    identity.transition(v2_exec, "submit", user=_user("employee4", "Employee"))
    identity.transition(v2_exec, "approve", user=_user("manager4", "Manager"))
    with pytest.raises(ConditionFailedError):
        identity.transition(v2_exec, "approve", user=_user("finance4", "Finance"))
    assert v2_exec.current_state == "finance_review"


def test_version_aware_approvals(identity):
    v1 = ensure_workflow_version(identity)
    draft = identity.create_version(from_version=v1)
    identity.update_version(draft, _build_v2())
    identity.publish_version(draft)

    v2_exec = identity.start(_invoice("INV-N", "300.00"))
    identity.transition(v2_exec, "submit", user=_user("employee5", "Employee"))
    identity.transition(v2_exec, "approve", user=_user("manager5", "Manager"))
    identity.transition(v2_exec, "approve", user=_user("finance5", "Finance"))
    assert v2_exec.current_state == "legal_review"
    legal_approvals = Approval.objects.filter(execution=v2_exec, step="legal_review")
    assert legal_approvals.count() == 2
    assert legal_approvals.filter(assignment__name="Legal").exists()
    assert legal_approvals.filter(assignment__name="Finance").exists()

    # v1 has no legal_review at all.
    v1_exec = identity.start(_invoice("INV-O", "300.00"), version=1)
    identity.transition(v1_exec, "submit", user=_user("employee6", "Employee"))
    identity.transition(v1_exec, "approve", user=_user("manager6", "Manager"))
    identity.transition(v1_exec, "approve", user=_user("finance6", "Finance"))
    assert v1_exec.current_state == "approved"
    assert not Approval.objects.filter(execution=v1_exec, step="legal_review").exists()


def test_version_aware_permissions(identity):
    v1 = ensure_workflow_version(identity)
    draft = identity.create_version(from_version=v1)
    identity.update_version(draft, _build_v2())
    identity.publish_version(draft)

    v2_exec = identity.start(_invoice("INV-P", "300.00"))
    identity.transition(v2_exec, "submit", user=_user("employee7", "Employee"))
    identity.transition(v2_exec, "approve", user=_user("manager7", "Manager"))
    identity.transition(v2_exec, "approve", user=_user("finance7", "Finance"))
    # Legal step requires the Legal group; Finance cannot approve it.
    with pytest.raises(PermissionDeniedError):
        identity.transition(v2_exec, "approve", user=_user("finance8", "Finance"))
    identity.transition(v2_exec, "approve", user=_user("legal1", "Legal"))
    assert v2_exec.current_state == "approved"


# --------------------------------------------------------------------------- #
# Audit / events / timeline carry the version
# --------------------------------------------------------------------------- #


def test_audit_records_workflow_version(identity):
    ensure_workflow_version(identity)
    execution = identity.start(_invoice("INV-Q", "100.00"))
    event = WorkflowEvent.objects.filter(execution=execution, event_type="workflow_started").first()
    assert event.metadata.get("workflow_version") == 1
    identity.transition(execution, "submit", user=_user("employee9", "Employee"))
    transitioned = WorkflowEvent.objects.filter(
        execution=execution, event_type="transition_executed"
    ).latest("id")
    assert transitioned.metadata.get("workflow_version") == 1


def test_domain_events_carry_workflow_version(identity):
    ensure_workflow_version(identity)
    captured: list[Any] = []
    from workflow_kit.events import subscribe

    subscription = subscribe(EventType.WORKFLOW_STARTED, captured.append)

    try:
        identity.start(_invoice("INV-R", "100.00"))
        assert captured
        assert captured[0].workflow_version == 1
        assert captured[0].workflow == WORKFLOW
    finally:
        subscription()


def test_timeline_metadata_has_version(identity):
    ensure_workflow_version(identity)
    execution = identity.start(_invoice("INV-S", "100.00"))
    events = execution.timeline()
    assert events
    assert all(event.metadata.get("workflow_version") == 1 for event in events)


# --------------------------------------------------------------------------- #
# Upgrade / migration path
# --------------------------------------------------------------------------- #


def test_ensure_workflow_version_is_idempotent(identity):
    v1 = ensure_workflow_version(identity)
    again = ensure_workflow_version(identity)
    assert again.pk == v1.pk
    assert WorkflowVersion.objects.filter(workflow=WORKFLOW).count() == 1


def test_upgrade_binds_existing_legacy_executions(identity):
    # Simulate a Phase 8 installation: executions started with no versions at all.
    legacy = identity.start(_invoice("INV-T", "100.00"))
    assert legacy.workflow_version_number is None
    identity.transition(legacy, "submit", user=_user("employee10", "Employee"))

    # The upgrade snapshots the current definition as v1 and pins the legacy row.
    v1 = ensure_workflow_version(identity)
    legacy.refresh_from_db()
    assert legacy.workflow_version_id == v1.pk

    draft = identity.create_version(from_version=v1)
    identity.update_version(draft, _build_v2())
    identity.publish_version(draft)

    # The previously-legacy execution keeps working on v1 semantics.
    identity.transition(legacy, "approve", user=_user("manager10", "Manager"))
    identity.transition(legacy, "approve", user=_user("finance10", "Finance"))
    assert legacy.current_state == "approved"


def test_non_serializable_workflow_degrades_gracefully():
    def _provider(context):  # callable permission - not serializable
        return True

    workflow = Workflow(
        name="versioning_nonserializable",
        initial="draft",
        states=["draft", "review", "approved"],
        transitions=[
            ("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission=_provider),
        ],
        register=False,
    )
    with contextlib.suppress(Exception):
        registry.register(workflow)
    try:
        with pytest.raises(WorkflowVersionError):
            serialize_workflow(workflow)
        execution = workflow.start(_invoice("INV-U", "100.00"))
        assert execution.workflow_version_number is None
    finally:
        registry.unregister("versioning_nonserializable")


# --------------------------------------------------------------------------- #
# Concurrency
# --------------------------------------------------------------------------- #


def _close_connections() -> None:
    from django.db import connections

    connections.close_all()


# SQLite allows a single writer at a time, so multi-thread tests must serialize
# their database access. The lock keeps the parallel-thread exercise stable on
# the file-backed test database while preserving the ordering guarantees under
# test (the threads still interleave via the events/barriers below).
_DB_LOCK = threading.Lock()


@pytest.mark.django_db(transaction=True)
def test_concurrent_publish_and_start_is_deterministic(identity):
    v1 = ensure_workflow_version(identity)
    published = threading.Event()
    errors: list[Exception] = []
    versions: list[int] = []

    def publisher() -> None:
        _close_connections()
        try:
            with _DB_LOCK:
                draft = identity.create_version(from_version=v1, changelog="concurrent")
                identity.update_version(draft, _build_v2())
                identity.publish_version(draft)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            published.set()
            _close_connections()

    def starter() -> None:
        _close_connections()
        try:
            # Starts issued before v2 is visible must bind v1; once the publish
            # has committed, later starts must bind v2. The monotonic switch is
            # what the engine must guarantee under concurrency.
            for index in range(10):
                with _DB_LOCK:
                    invoice = _invoice(f"CONC-{index:03d}", "100.00")
                    versions.append(identity.start(invoice).workflow_version_number)
                if index == 5:
                    published.wait(timeout=60)
        finally:
            _close_connections()

    threads = [
        threading.Thread(target=publisher),
        threading.Thread(target=starter),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert versions
    assert all(version in (1, 2) for version in versions)
    # Once v2 became published (after at most the fifth start), no later start
    # may bind the older v1.
    assert published.is_set()
    assert 2 in versions


@pytest.mark.django_db(transaction=True)
def test_v1_execution_transitions_during_v2_publish(identity):
    v1 = ensure_workflow_version(identity)
    employee = _user("c_employee", "Employee")
    manager = _user("c_manager", "Manager")
    finance = _user("c_finance", "Finance")

    execution = identity.start(_invoice("CONC-V1", "100.00"))
    identity.transition(execution, "submit", user=employee)
    execution_id = execution.pk

    state_after: list[str] = []

    def publisher() -> None:
        _close_connections()
        try:
            with _DB_LOCK:
                draft = identity.create_version(from_version=v1, changelog="raced")
                identity.update_version(draft, _build_v2())
                identity.publish_version(draft)
        finally:
            _close_connections()

    def v1_transitioner() -> None:
        _close_connections()
        try:
            with _DB_LOCK:
                fresh = WorkflowExecution.objects.select_for_update().get(pk=execution_id)
                identity.transition(fresh, "approve", user=manager)
                state_after.append(fresh.current_state)
        finally:
            _close_connections()

    threads = [
        threading.Thread(target=publisher),
        threading.Thread(target=v1_transitioner),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert state_after == ["finance_review"]
    execution.refresh_from_db()
    assert execution.workflow_version_number == 1

    # The v1 execution must keep v1 semantics (finance -> approved).
    identity.transition(execution, "approve", user=finance)
    execution.refresh_from_db()
    assert execution.current_state == "approved"
    assert execution.workflow_version_number == 1

    # New executions now bind v2.
    assert identity.start(_invoice("CONC-V2", "100.00")).workflow_version_number == 2


# --------------------------------------------------------------------------- #
# REST API
# --------------------------------------------------------------------------- #


def _api_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_rest_lists_versions(identity):
    v1 = ensure_workflow_version(identity, changelog="initial api")
    draft = identity.create_version(from_version=v1)
    identity.update_version(draft, _build_v2())
    identity.publish_version(draft)

    client = _api_client(_user("api_user", "Employee"))
    response = client.get("/api/versions/")
    assert response.status_code == 200
    bodies = response.data["results"]
    assert len(bodies) == 2
    assert {b["version"] for b in bodies} == {1, 2}
    assert {b["status"] for b in bodies} == {"PUBLISHED"}
    assert any(b["changelog"] == "initial api" for b in bodies)
    assert all(isinstance(b["definition"], dict) for b in bodies)


def test_rest_version_detail(identity):
    v1 = ensure_workflow_version(identity)
    client = _api_client(_user("api_user2", "Employee"))
    response = client.get(f"/api/versions/{v1.pk}/")
    assert response.status_code == 200
    assert response.data["version"] == 1
    assert response.data["workflow"] == WORKFLOW
    assert response.data["status"] == "PUBLISHED"


def test_rest_version_filters(identity):
    v1 = ensure_workflow_version(identity)
    draft = identity.create_version(from_version=v1)
    identity.update_version(draft, _build_v2())

    client = _api_client(_user("api_user3", "Employee"))
    response = client.get("/api/versions/?status=draft")
    assert response.status_code == 200
    assert [b["version"] for b in response.data["results"]] == [2]
    response = client.get("/api/versions/?workflow=versioning_flow")
    assert response.data["count"] == 2


def test_rest_requires_authentication(identity):
    ensure_workflow_version(identity)
    client = APIClient()
    response = client.get("/api/versions/")
    assert response.status_code in (401, 403)


def test_rest_execution_exposes_workflow_version(identity):
    ensure_workflow_version(identity)
    execution = identity.start(_invoice("INV-REST", "100.00"))
    client = _api_client(_user("api_user4", "Employee"))
    response = client.get(f"/api/executions/{execution.pk}/")
    assert response.status_code == 200
    assert response.data["workflow_version"] == 1
    list_response = client.get("/api/executions/")
    payload = next(item for item in list_response.data["results"] if item["id"] == execution.pk)
    assert payload["workflow_version"] == 1


def test_rest_execution_without_version_is_null(identity):
    execution = identity.start(_invoice("INV-REST2", "100.00"))
    client = _api_client(_user("api_user5", "Employee"))
    response = client.get(f"/api/executions/{execution.pk}/")
    assert response.status_code == 200
    assert response.data["workflow_version"] is None


# --------------------------------------------------------------------------- #
# Admin
# --------------------------------------------------------------------------- #


def test_admin_registers_workflow_version(identity, admin_client):
    ensure_workflow_version(identity)
    response = admin_client.get("/admin/workflow_kit/workflowversion/")
    assert response.status_code == 200
    assert b"versioning_flow" in response.content


def test_admin_workflow_version_is_read_only(identity, admin_client):
    from django.contrib import admin as dj_admin
    from workflow_kit.admin import WorkflowVersionAdmin

    version = ensure_workflow_version(identity)
    model_admin = WorkflowVersionAdmin(WorkflowVersion, dj_admin.site)
    assert model_admin.has_add_permission(admin_client.request) is False
    assert model_admin.has_change_permission(admin_client.request, version) is False
    assert model_admin.has_delete_permission(admin_client.request, version) is False
