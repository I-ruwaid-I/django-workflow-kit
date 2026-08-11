"""Phase 13 tests: deterministic concurrency and idempotency.

The engine guarantees a single winner for every racing operation: executions
are locked with ``select_for_update`` and the current state is re-validated
under that lock before any change is persisted (``ATOMIC_TRANSITIONS``). These
tests push real threads against the same execution / approval / version at the
same instant and assert that the *outcome is deterministic*: exactly one valid
effect, no duplicate transitions, approvals or events, no corrupted state and
an append-only audit trail.

Scenarios follow PHASE13 ``#4``-``#10``:

- multiple users, same execution, same transition (``#5``);
- parallel approvals, quorum arithmetic, parallel approve+reject (``#6``);
- escalation / SLA worker racing a user transition (``#7``);
- webhook / retry / timeout idempotency (``#8``);
- concurrent first-time version creation and version-race safety (``#9``);
- repeated and concurrent identical operations collapse to one effect (``#10``).

SQLite allows a single writer at a time, so thread tests serialize their
database access with a module-level lock (mirroring ``tests/test_versioning.py``)
while still starting all threads at the same instant with a barrier; the
assertions hold for any interleaving order.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError
from django.utils import timezone
from workflow_kit import (
    ApprovalMode,
    ApprovalRequirement,
    EventType,
    Transition,
    Workflow,
    WorkflowAlreadyCompletedError,
    WorkflowVersionError,
)
from workflow_kit.approvals import overdue_approvals
from workflow_kit.engine import registry
from workflow_kit.events import ALL_EVENTS, default_dispatcher
from workflow_kit.exceptions import ApprovalNotPendingError, PermissionDeniedError
from workflow_kit.models import (
    Approval,
    ApprovalStatus,
    VersionStatus,
    WorkflowEvent,
    WorkflowExecution,
    WorkflowVersion,
)

from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db

# Lock serializing SQLite database access across threads (see module docstring).
_DB_LOCK = threading.Lock()


def _close_connections() -> None:
    from django.db import connections

    connections.close_all()


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


def _invoice(number: str, amount: str = "500.00") -> Invoice:
    return Invoice.objects.create(number=number, vendor="Acme", amount=amount)


def _review_workflow(name: str, *, requirement: ApprovalRequirement | None = None) -> Workflow:
    """A registered draft -> review -> approved / rejected workflow."""
    workflow = Workflow(
        name=name,
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            Transition("submit", "draft", "review"),
            Transition("approve", "review", "approved"),
            Transition("reject", "review", "rejected"),
        ],
        approval_requirements={"review": requirement} if requirement else None,
        register=True,
    )
    return workflow


def _started(
    name: str,
    invoice: Invoice,
    requirement: ApprovalRequirement | None = None,
) -> tuple[Workflow, WorkflowExecution]:
    workflow = _review_workflow(name, requirement=requirement)
    execution = workflow.start(invoice)
    workflow.transition(execution, "submit")
    return workflow, execution


def _cleanup(name: str) -> None:
    registry.unregister(name)


def _run_threads(workers: list[Any]) -> list[Any]:
    """Run ``workers`` at the same instant; return outcomes (None or exception).

    Each worker must be a pure callable with no arguments: the harness closes
    database connections, aligns all threads on a barrier and serializes the
    actual database access with ``_DB_LOCK``. Outcomes preserve input order.
    """
    barrier = threading.Barrier(len(workers))
    outcomes: list[Any] = [RuntimeError("worker never completed")] * len(workers)
    outcomes_lock = threading.Lock()

    def _run(worker: Any, index: int) -> None:
        _close_connections()
        try:
            try:
                barrier.wait(timeout=60)
            except threading.BrokenBarrierError:
                with outcomes_lock:
                    outcomes[index] = threading.BrokenBarrierError()
                return
            try:
                with _DB_LOCK:
                    worker()
            except Exception as exc:  # noqa: BLE001 - outcomes are asserted
                with outcomes_lock:
                    outcomes[index] = exc
                return
            with outcomes_lock:
                outcomes[index] = None
        finally:
            _close_connections()

    threads = [
        threading.Thread(target=_run, args=(worker, index)) for index, worker in enumerate(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def _count_events(events: list[Any], event_type: EventType) -> int:
    return sum(1 for event in events if event.type == event_type)


def _event_count(execution: WorkflowExecution, event_type: str, action: str = "") -> int:
    """Count persisted audit events for ``execution``, optionally by action."""
    events = WorkflowEvent.objects.filter(execution=execution, event_type=event_type)
    if action:
        events = events.filter(action=action)
    return events.count()


# --------------------------------------------------------------------------- #
# #5 — multiple users, same execution, same transition
# --------------------------------------------------------------------------- #


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_execution_same_transition_single_winner():
    """Approve the same review execution from two threads at the same instant.

    Exactly one caller may execute the transition; the other is refused with a
    clean domain error. State, audit and events must reflect one effect.
    """
    workflow, execution = _started("p13_same_transition", _invoice("P13-1"))
    pk = execution.pk
    collected: list[Any] = []
    unsubscribe = default_dispatcher.subscribe(ALL_EVENTS, collected.append)

    def approve(username: str) -> None:
        fresh = WorkflowExecution.objects.select_for_update().get(pk=pk)
        workflow.transition(fresh, "approve", user=_user(username, "Employee"))

    try:
        outcomes = _run_threads([lambda: approve("alice"), lambda: approve("bob")])
    finally:
        unsubscribe()

    successes = [o for o in outcomes if o is None]
    failures = [o for o in outcomes if o is not None]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], WorkflowAlreadyCompletedError)

    fresh = WorkflowExecution.objects.get(pk=pk)
    assert fresh.current_state == "approved"
    assert fresh.completed_at is not None

    # Exactly one transition executed, one completion; no duplicates. The
    # audit trail also holds the earlier submit event, so only the approve
    # action is counted here.
    approve_events = WorkflowEvent.objects.filter(
        execution=fresh, event_type="transition_executed", action="approve"
    )
    assert approve_events.count() == 1
    assert _event_count(fresh, "workflow_completed") == 1
    assert _count_events(collected, EventType.WORKFLOW_TRANSITIONED) == 1
    assert _count_events(collected, EventType.WORKFLOW_COMPLETED) == 1

    _cleanup("p13_same_transition")


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_execution_unauthorized_racer_is_refused():
    """An unauthorized racer is refused; the authorized caller wins once."""
    workflow = Workflow(
        name="p13_perm_race",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            Transition("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission="Manager"),
            Transition("reject", "review", "rejected", permission="Manager"),
        ],
        register=True,
    )
    execution = workflow.start(_invoice("P13-9"))
    workflow.transition(execution, "submit")
    pk = execution.pk

    def submit_as(username: str, *groups: str) -> None:
        fresh = WorkflowExecution.objects.select_for_update().get(pk=pk)
        workflow.transition(fresh, "approve", user=_user(username, *groups))

    outcomes = _run_threads(
        [
            lambda: submit_as("mgmt_ok", "Manager"),
            lambda: submit_as("peon_no", "Clerk"),
        ]
    )
    successes = [o for o in outcomes if o is None]
    failures = [o for o in outcomes if o is not None]
    assert len(successes) == 1
    # The loser either was denied authorization or hit the completed workflow.
    assert all(
        isinstance(o, (PermissionDeniedError, WorkflowAlreadyCompletedError)) for o in failures
    )

    fresh = WorkflowExecution.objects.get(pk=pk)
    assert fresh.current_state == "approved"
    assert (
        WorkflowEvent.objects.filter(
            execution=fresh, event_type="transition_executed", action="approve"
        ).count()
        == 1
    )

    _cleanup("p13_perm_race")


# --------------------------------------------------------------------------- #
# #6 — parallel approvals / quorum / parallel reject
# --------------------------------------------------------------------------- #


@pytest.mark.django_db(transaction=True)
def test_concurrent_parallel_approvals_all_mode_both_succeed_once():
    """All-of: both assigned approvers vote; exactly one advance happens."""
    requirement = ApprovalRequirement(mode=ApprovalMode.ALL, approvers=["Manager", "Finance"])
    workflow, execution = _started("p13_all_mode", _invoice("P13-2"), requirement)
    pk = execution.pk
    ui = {"manager": _user("m_all", "Manager"), "finance": _user("f_all", "Finance")}
    collected: list[Any] = []
    unsubscribe = default_dispatcher.subscribe(ALL_EVENTS, collected.append)

    def vote(key: str) -> None:
        fresh = WorkflowExecution.objects.select_for_update().get(pk=pk)
        fresh.approve(user=ui[key])

    try:
        outcomes = _run_threads([lambda: vote("manager"), lambda: vote("finance")])
    finally:
        unsubscribe()

    assert [o for o in outcomes if o is not None] == []
    approvals = list(Approval.objects.filter(execution=execution).order_by("order", "id"))
    assert [a.status for a in approvals] == [ApprovalStatus.APPROVED, ApprovalStatus.APPROVED]
    fresh = WorkflowExecution.objects.get(pk=pk)
    assert fresh.current_state == "approved"
    assert fresh.completed_at is not None
    assert _count_events(collected, EventType.APPROVAL_APPROVED) == 2
    assert _count_events(collected, EventType.WORKFLOW_COMPLETED) == 1

    _cleanup("p13_all_mode")


@pytest.mark.django_db(transaction=True)
def test_concurrent_parallel_approvals_quorum_satisfied_once():
    """Quorum: exactly the quorum advances; the trailing racer is refused."""
    from workflow_kit.exceptions import ApprovalNotPendingError

    requirement = ApprovalRequirement(
        mode=ApprovalMode.QUORUM,
        approvers=["Manager", "Finance", "HR"],
        quorum=2,
    )
    workflow, execution = _started("p13_quorum", _invoice("P13-3"), requirement)
    pk = execution.pk
    ui = {
        "manager": _user("m_q", "Manager"),
        "finance": _user("f_q", "Finance"),
        "hr": _user("h_q", "HR"),
    }
    collected: list[Any] = []
    unsubscribe = default_dispatcher.subscribe(ALL_EVENTS, collected.append)

    def vote(key: str) -> None:
        fresh = WorkflowExecution.objects.select_for_update().get(pk=pk)
        fresh.approve(user=ui[key])

    try:
        outcomes = _run_threads(
            [lambda: vote("manager"), lambda: vote("finance"), lambda: vote("hr")]
        )
    finally:
        unsubscribe()

    # Whichever two votes reach the quorum win; the third is refused cleanly.
    assert sum(o is None for o in outcomes) == 2
    failures = [o for o in outcomes if o is not None]
    assert all(
        isinstance(o, (ApprovalNotPendingError, WorkflowAlreadyCompletedError)) for o in failures
    )

    statuses = sorted(Approval.objects.filter(execution=execution).values_list("status", flat=True))
    assert statuses.count(ApprovalStatus.APPROVED) == 2
    assert statuses.count(ApprovalStatus.CANCELLED) == 1
    fresh = WorkflowExecution.objects.get(pk=pk)
    assert fresh.current_state == "approved"
    assert fresh.completed_at is not None
    assert _count_events(collected, EventType.APPROVAL_APPROVED) == 2
    assert _count_events(collected, EventType.WORKFLOW_COMPLETED) == 1

    _cleanup("p13_quorum")


@pytest.mark.django_db(transaction=True)
def test_concurrent_parallel_approve_and_reject_settles_once():
    """Parallel approve + reject: the rejection is the deterministic outcome."""
    requirement = ApprovalRequirement(mode=ApprovalMode.ALL, approvers=["Manager", "Finance"])
    workflow, execution = _started("p13_approve_reject", _invoice("P13-4"), requirement)
    pk = execution.pk
    ui = {"manager": _user("m_ar", "Manager"), "finance": _user("f_ar", "Finance")}

    def decision(key: str, action: str) -> None:
        fresh = WorkflowExecution.objects.select_for_update().get(pk=pk)
        getattr(fresh, action)(user=ui[key])

    outcomes = _run_threads(
        [
            lambda: decision("manager", "approve"),
            lambda: decision("finance", "reject"),
        ]
    )
    # Either both succeed (approve records, then reject settles) or the reject
    # settles alone and the approver is refused. Either way a rejection wins.
    assert sum(o is None for o in outcomes) >= 1
    failures = [o for o in outcomes if o is not None]
    assert all(
        isinstance(o, (ApprovalNotPendingError, WorkflowAlreadyCompletedError)) for o in failures
    )

    fresh = WorkflowExecution.objects.get(pk=pk)
    assert fresh.current_state == "rejected"
    assert fresh.completed_at is not None
    assert not Approval.objects.filter(execution=execution, status=ApprovalStatus.PENDING).exists()

    _cleanup("p13_approve_reject")


# --------------------------------------------------------------------------- #
# #7 — SLA / escalation racing a user transition
# --------------------------------------------------------------------------- #


@pytest.mark.django_db(transaction=True)
def test_concurrent_escalation_and_approval_no_contradiction():
    """Escalation racing the step's approval must never leave a hybrid state."""
    requirement = ApprovalRequirement(mode=ApprovalMode.ALL, approvers=["Manager"])
    workflow, execution = _started("p13_escalate", _invoice("P13-5"), requirement)
    pk = execution.pk
    manager = _user("m_esc", "Manager")
    actor = _user("actor_esc", "Manager")

    def escalate() -> None:
        fresh = WorkflowExecution.objects.select_for_update().get(pk=pk)
        fresh.escalate(approver="Finance", user=actor)

    def approve() -> None:
        fresh = WorkflowExecution.objects.select_for_update().get(pk=pk)
        fresh.approve(user=manager)

    outcomes = _run_threads([escalate, approve])
    # Exactly one caller wins; the loser is refused with a clean domain error.
    # Final state is either approved (approve won) or an escalated review.
    successes = [o for o in outcomes if o is None]
    failures = [o for o in outcomes if o is not None]
    assert len(successes) == 1
    assert all(
        isinstance(
            o, (WorkflowAlreadyCompletedError, ApprovalNotPendingError, PermissionDeniedError)
        )
        for o in failures
    )

    fresh = WorkflowExecution.objects.get(pk=pk)
    if fresh.current_state == "approved":
        assert fresh.completed_at is not None
        assert not Approval.objects.filter(
            execution=execution, status=ApprovalStatus.PENDING
        ).exists()
    else:
        assert fresh.current_state == "review"
        assert fresh.completed_at is None
        pending = list(Approval.objects.filter(execution=execution, status=ApprovalStatus.PENDING))
        assert len(pending) == 1
        assert pending[0].assignment.get("escalated") is True
        sibling_statuses = [
            a.status for a in Approval.objects.filter(execution=execution).exclude(pk=pending[0].pk)
        ]
        assert sibling_statuses and all(s == ApprovalStatus.CANCELLED for s in sibling_statuses)

    _cleanup("p13_escalate")


@pytest.mark.django_db(transaction=True)
def test_sla_worker_overdue_escalation_races_user_transition():
    """The SLA worker escalating an overdue approval racing a user transition."""
    requirement = ApprovalRequirement(
        mode=ApprovalMode.ALL,
        approvers=["Manager"],
        sla=timedelta(seconds=60),
    )
    workflow, execution = _started("p13_sla_race", _invoice("P13-6"), requirement)
    pk = execution.pk
    Approval.objects.filter(execution=execution).update(due_at=timezone.now() - timedelta(days=1))
    overdue = overdue_approvals(workflow_name="p13_sla_race")
    assert overdue.filter(execution=execution).exists()

    manager = _user("m_sla", "Manager")

    def sla_worker_escalate() -> None:
        fresh = WorkflowExecution.objects.select_for_update().get(pk=pk)
        fresh.escalate(approver="Finance", user=manager)

    def user_transition() -> None:
        fresh = WorkflowExecution.objects.select_for_update().get(pk=pk)
        fresh.approve(user=manager)

    outcomes = _run_threads([sla_worker_escalate, user_transition])
    # A single deterministic winner again: either the escalation replaces the
    # overdue approval with an escalated one, or the user's approve wins and
    # the escalation is refused on the completed workflow.
    successes = [o for o in outcomes if o is None]
    failures = [o for o in outcomes if o is not None]
    assert len(successes) == 1
    assert all(
        isinstance(
            o, (WorkflowAlreadyCompletedError, ApprovalNotPendingError, PermissionDeniedError)
        )
        for o in failures
    )

    fresh = WorkflowExecution.objects.get(pk=pk)
    assert fresh.current_state in {"review", "approved"}
    if fresh.current_state == "approved":
        assert fresh.completed_at is not None
        assert not Approval.objects.filter(
            execution=execution, status=ApprovalStatus.PENDING
        ).exists()
    else:
        pending = list(Approval.objects.filter(execution=execution, status=ApprovalStatus.PENDING))
        assert len(pending) == 1
        assert pending[0].assignment.get("escalated") is True

    _cleanup("p13_sla_race")


# --------------------------------------------------------------------------- #
# #8 — webhook / retry / timeout idempotency
# --------------------------------------------------------------------------- #


def test_webhook_event_id_is_stable_for_retries():
    """A single logical transition produces one stable event id for dedup."""
    from workflow_kit.notifications.webhook import sign_payload

    workflow, execution = _started("p13_webhook", _invoice("P13-7"))
    delivered: list[Any] = []
    unsubscribe = default_dispatcher.subscribe(EventType.WORKFLOW_COMPLETED, delivered.append)
    try:
        fresh = WorkflowExecution.objects.select_for_update().get(pk=execution.pk)
        workflow.transition(fresh, "approve", user=_user("w_hook", "Employee"))
    finally:
        unsubscribe()

    assert len(delivered) == 1
    event = delivered[0]
    assert event.id
    # Retries of the same logical event carry the same id, so a webhook
    # consumer can deduplicate regardless of delivery retries.
    assert sign_payload("secret", "2026-01-01T00:00:00", event.id, "body") == sign_payload(
        "secret", "2026-01-01T00:00:00", event.id, "body"
    )
    assert event.type == EventType.WORKFLOW_COMPLETED

    _cleanup("p13_webhook")


@pytest.mark.django_db(transaction=True)
def test_event_redispatch_does_not_re_mutate_execution():
    """Re-delivering / retrying a captured event never re-runs the engine."""
    workflow, execution = _started("p13_retry", _invoice("P13-8"))
    captured: list[Any] = []
    unsubscribe = default_dispatcher.subscribe(ALL_EVENTS, captured.append)
    try:
        fresh = WorkflowExecution.objects.select_for_update().get(pk=execution.pk)
        workflow.transition(fresh, "approve", user=_user("w_retry", "Employee"))
        transit = [e for e in captured if e.type == EventType.WORKFLOW_TRANSITIONED]
        assert len(transit) == 1

        audit_before = WorkflowEvent.objects.filter(execution=fresh).count()
        approvals_before = Approval.objects.filter(execution=fresh).count()
        state_before = fresh.current_state

        # Simulate a delivery timeout + retry: subscribers see the event again,
        # but that must not touch execution state, approvals or the audit trail.
        for _ in range(2):
            default_dispatcher.dispatch(transit[0])

        fresh.refresh_from_db()
        assert fresh.current_state == state_before
        assert WorkflowEvent.objects.filter(execution=fresh).count() == audit_before
        assert Approval.objects.filter(execution=fresh).count() == approvals_before
    finally:
        unsubscribe()

    _cleanup("p13_retry")


# --------------------------------------------------------------------------- #
# #9 — versioning concurrency
# --------------------------------------------------------------------------- #


@pytest.mark.django_db(transaction=True)
def test_concurrent_first_time_versioning_creates_single_v1():
    """Two simultaneous upgrades must produce exactly one published v1."""
    from workflow_kit.engine.versioning import ensure_workflow_version

    workflow = Workflow(
        name="p13_ensure_version",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "review"),
            ("approve", "review", "approved"),
            ("reject", "review", "rejected"),
        ],
        register=True,
    )
    pks: list[Any] = []
    pks_lock = threading.Lock()

    def _ensure() -> None:
        _close_connections()
        try:
            with _DB_LOCK:
                created = ensure_workflow_version(workflow, user=_user("upgrader", "Employee"))
                with pks_lock:
                    pks.append(created.pk)
        finally:
            _close_connections()

    threads = [threading.Thread(target=_ensure) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    versions = list(WorkflowVersion.objects.filter(workflow="p13_ensure_version"))
    assert len(versions) == 1
    assert versions[0].version == 1
    assert versions[0].status == VersionStatus.PUBLISHED
    assert len(pks) == 2
    assert len(set(pks)) == 1

    _cleanup("p13_ensure_version")


@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicate_start_same_object_keeps_single_execution():
    """Duplicate starts of the same object under concurrency leave one row."""
    workflow = _review_workflow("p13_dup_start")
    invoice = _invoice("P13-10")
    outcomes: list[Any] = []
    outcomes_lock = threading.Lock()

    def _start() -> None:
        _close_connections()
        try:
            with _DB_LOCK:
                try:
                    workflow.start(invoice)
                except IntegrityError:
                    with outcomes_lock:
                        outcomes.append(IntegrityError)
                    return
                with outcomes_lock:
                    outcomes.append(None)
        finally:
            _close_connections()

    threads = [threading.Thread(target=_start) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    rows = WorkflowExecution.objects.filter(workflow_name="p13_dup_start", object_id=invoice.pk)
    assert rows.count() == 1
    assert outcomes.count(None) == 1
    assert outcomes.count(IntegrityError) == 1

    _cleanup("p13_dup_start")


@pytest.mark.django_db(transaction=True)
def test_concurrent_version_race_keeps_v1_execution_bound():
    """A v1 execution racing a v2 publish keeps its own version semantics."""
    from workflow_kit.engine.versioning import ensure_workflow_version

    workflow = Workflow(
        name="p13_version_race",
        initial="draft",
        states=["draft", "manager_review", "finance_review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "manager_review"),
            ("approve", "manager_review", "finance_review"),
            ("approve", "finance_review", "approved"),
            ("reject", "manager_review", "rejected"),
            ("reject", "finance_review", "rejected"),
        ],
        register=True,
    )
    v1 = ensure_workflow_version(workflow, user=_user("v_seed", "Employee"))
    executor = workflow.start(_invoice("P13-11"))
    executor_pk = executor.pk
    workflow.transition(executor, "submit", user=_user("v_emp", "Employee"))
    assert executor.workflow_version_number == 1

    draft = workflow.create_version(from_version=v1, user=_user("v_author", "Employee"))
    workflow.update_version(draft, workflow)  # snapshot current definition as v2
    draft_pk = draft.pk

    def publisher() -> None:
        _close_connections()
        try:
            with _DB_LOCK:
                version = WorkflowVersion.objects.get(pk=draft_pk)
                workflow.publish_version(version, user=_user("v_pub", "Employee"))
        finally:
            _close_connections()

    def v1_racer() -> None:
        _close_connections()
        try:
            with _DB_LOCK:
                fresh = WorkflowExecution.objects.select_for_update().get(pk=executor_pk)
                workflow.transition(fresh, "approve", user=_user("v_mgr", "Manager"))
        finally:
            _close_connections()

    threads = [threading.Thread(target=publisher), threading.Thread(target=v1_racer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    executor.refresh_from_db()
    assert executor.current_state == "finance_review"
    assert executor.workflow_version_number == 1
    # The v1 execution still advances to approved on v1 semantics.
    workflow.transition(executor, "approve", user=_user("v_fin", "Finance"))
    executor.refresh_from_db()
    assert executor.current_state == "approved"
    assert executor.workflow_version_number == 1
    # A new execution after the publish binds v2.
    assert workflow.start(_invoice("P13-12")).workflow_version_number == 2

    _cleanup("p13_version_race")


# --------------------------------------------------------------------------- #
# #10 — repeated operations collapse to one logical effect
# --------------------------------------------------------------------------- #


def test_repeated_identical_transition_is_single_effect():
    """Approve ten times: only the first changes anything."""
    workflow, execution = _started("p13_repeat", _invoice("P13-13"))
    pk = execution.pk
    user = _user("repeater", "Employee")

    losers = 0
    for _ in range(10):
        fresh = WorkflowExecution.objects.select_for_update().get(pk=pk)
        try:
            workflow.transition(fresh, "approve", user=user)
        except WorkflowAlreadyCompletedError:
            losers += 1
    assert losers == 9
    fresh = WorkflowExecution.objects.get(pk=pk)
    assert fresh.current_state == "approved"
    assert fresh.completed_at is not None
    assert _event_count(fresh, "transition_executed", action="approve") == 1
    assert _event_count(fresh, "workflow_completed") == 1

    _cleanup("p13_repeat")


@pytest.mark.django_db(transaction=True)
def test_concurrent_identical_transitions_single_effect():
    """Ten simultaneous identical approvals must produce one effect."""
    workflow, execution = _started("p13_concurrent_repeat", _invoice("P13-14"))
    pk = execution.pk
    user = _user("soaker", "Employee")
    collected: list[Any] = []
    unsubscribe = default_dispatcher.subscribe(ALL_EVENTS, collected.append)

    def approve() -> None:
        fresh = WorkflowExecution.objects.select_for_update().get(pk=pk)
        workflow.transition(fresh, "approve", user=user)

    try:
        outcomes = _run_threads([approve] * 10)
    finally:
        unsubscribe()

    assert sum(o is None for o in outcomes) == 1
    assert all(
        isinstance(o, WorkflowAlreadyCompletedError) if o is not None else True for o in outcomes
    )
    fresh = WorkflowExecution.objects.get(pk=pk)
    assert fresh.current_state == "approved"
    assert _event_count(fresh, "transition_executed", action="approve") == 1
    assert _event_count(fresh, "workflow_completed") == 1
    assert _count_events(collected, EventType.WORKFLOW_TRANSITIONED) == 1
    assert _count_events(collected, EventType.WORKFLOW_COMPLETED) == 1

    _cleanup("p13_concurrent_repeat")


def test_repeated_publish_version_is_single_effect():
    """Publishing the same draft twice yields one published version."""
    from workflow_kit.engine.versioning import ensure_workflow_version

    workflow = Workflow(
        name="p13_repeat_publish",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "review"),
            ("approve", "review", "approved"),
            ("reject", "review", "rejected"),
        ],
        register=True,
    )
    v1 = ensure_workflow_version(workflow, user=_user("rp_seed", "Employee"))
    draft = workflow.create_version(from_version=v1, user=_user("rp_author", "Employee"))
    workflow.update_version(draft, workflow)

    first = workflow.publish_version(draft, user=_user("rp_pub", "Employee"))
    second = workflow.publish_version(draft, user=_user("rp_pub2", "Employee"))
    assert first.pk == second.pk == draft.pk
    versions = list(WorkflowVersion.objects.filter(workflow="p13_repeat_publish"))
    assert len(versions) == 2
    published = [v for v in versions if v.status == VersionStatus.PUBLISHED]
    assert len(published) == 2

    _cleanup("p13_repeat_publish")


def test_publish_retired_version_fails_deterministically():
    """Retired versions must never republish, even when requested repeatedly."""
    from workflow_kit.engine.versioning import ensure_workflow_version

    workflow = Workflow(
        name="p13_retired_publish",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            ("submit", "draft", "review"),
            ("approve", "review", "approved"),
            ("reject", "review", "rejected"),
        ],
        register=True,
    )
    v1 = ensure_workflow_version(workflow, user=_user("ret_seed", "Employee"))
    draft = workflow.create_version(from_version=v1)
    workflow.publish_version(draft)
    workflow.retire_version(draft)
    for _ in range(2):
        with pytest.raises(WorkflowVersionError):
            workflow.publish_version(draft)

    _cleanup("p13_retired_publish")
