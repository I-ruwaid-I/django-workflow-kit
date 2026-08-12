"""Phase 13 tests: migration / upgrade safety (PHASE13 ``#24``-``#25``).

These tests exercise a realistic upgrade: an installation on the Phase 12
schema (``0005``) is migrated forward to the Phase 13 schema (``0006``) while
carrying real data, and the Phase 13 migration is verified to reverse cleanly.

``0006`` only adds two indexes on ``WorkflowExecution`` (``current_state`` and
``-started_at``), so the upgrade is a pure index-add: all rows and analytics
must survive untouched and the migration must roll back without data loss.

The checks run against the real migration graph using
:class:`django.db.migrations.executor.MigrationExecutor` so they reflect the
actual migration files on disk, not a hand-written schema.

These tests run with ``transaction=True`` because they execute real SQLite
DDL (schema editor), which cannot run inside a transaction wrapper. Every test
restores the schema to the Phase 13 leaf in a ``finally`` block so the shared
test database never left in a migrated-back state.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connections, migrations
from django.db.migrations.executor import MigrationExecutor
from workflow_kit.analytics.metrics import execution_metrics
from workflow_kit.models import (
    Approval,
    ApprovalStatus,
    WorkflowComment,
    WorkflowEvent,
    WorkflowExecution,
    WorkflowVersion,
)

PHASE12_LEAF = "0005_alter_workflowevent_event_type_workflowattachment_and_more"
PHASE13_LEAF = "0006_workflowexecution_workflow_ki_current_087898_idx_and_more"
CURRENT_LEAF = "0007_workflowexecution_view_analytics_permission"

User = get_user_model()


def _migrate(executor: MigrationExecutor, target: str) -> None:
    """Migrate the ``workflow_kit`` app to ``target`` (a leaf name)."""
    executor.migrate([("workflow_kit", target)])


def _fresh_executor() -> MigrationExecutor:
    """Return a fresh executor; re-planning needs a new instance after a reverse."""
    return MigrationExecutor(connections["default"])


def _current_leaf(executor: MigrationExecutor) -> str:
    applied = {
        name
        for app_label, name in executor.recorder.applied_migrations()
        if app_label == "workflow_kit"
    }
    return max(applied)


def _index_names() -> set[str]:
    """Return the index names currently defined on the execution table."""
    connection = connections["default"]
    table = WorkflowExecution._meta.db_table
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table)
    return {name for name, definition in constraints.items() if definition["index"]}


@pytest.mark.django_db(transaction=True)
def test_phase13_migration_is_reversible():
    """The Phase 13 migration (0005 -> 0006) reverses cleanly.

    The forward step adds the two execution indexes; reversing must remove them
    again; re-applying must re-create them.
    """
    connection = connections["default"]
    try:
        executor = MigrationExecutor(connection)
        assert _current_leaf(executor) == CURRENT_LEAF

        _migrate(executor, PHASE12_LEAF)
        assert _current_leaf(executor) == PHASE12_LEAF

        index_names = _index_names()
        assert "workflow_ki_current_087898_idx" not in index_names
        assert "workflow_ki_started_152542_idx" not in index_names

        executor = _fresh_executor()
        _migrate(executor, PHASE13_LEAF)
        assert _current_leaf(executor) == PHASE13_LEAF
        index_names = _index_names()
        assert "workflow_ki_current_087898_idx" in index_names
        assert "workflow_ki_started_152542_idx" in index_names

        # The migration file declares exactly the two indexes we expect.
        loader = migrations.loader.MigrationLoader(connection)
        node = loader.graph.nodes[("workflow_kit", PHASE13_LEAF)]
        add_indexes = [op for op in node.operations if isinstance(op, migrations.AddIndex)]
        assert len(add_indexes) == 2
        fields: set[str] = set()
        for op in add_indexes:
            fields.update(op.index.fields)
        assert fields == {"current_state", "-started_at"}
    finally:
        _migrate(MigrationExecutor(connection), CURRENT_LEAF)


@pytest.mark.django_db(transaction=True)
def test_phase12_data_survives_upgrade_to_phase13(django_user_model):
    """Rows written on the Phase 12 schema survive the Phase 13 migration.

    The upgrade must preserve executions, workflow versions, approvals, the
    audit trail, comments and analytics correctness.
    """
    from django.utils import timezone

    connection = connections["default"]
    try:
        executor = MigrationExecutor(connection)

        # 1. Move the schema back to the Phase 12 state.
        _migrate(executor, PHASE12_LEAF)
        assert _current_leaf(executor) == PHASE12_LEAF

        # 2. Write realistic Phase 12 data.
        user = django_user_model.objects.create_user(
            username="upgrade_bob", password="pw", email="bob@example.invalid"
        )
        content_type = ContentType.objects.get_for_model(User)

        version = WorkflowVersion.objects.create(
            workflow="upgrade_flow",
            version=1,
            status="PUBLISHED",
            definition={"name": "upgrade_flow", "initial": "draft"},
            changelog="phase12",
            created_by=user,
        )
        execution = WorkflowExecution.objects.create(
            workflow_name="upgrade_flow",
            content_type=content_type,
            object_id=42,
            current_state="review",
            workflow_version=version,
            started_at=timezone.now() - timezone.timedelta(days=2),
        )
        approval = Approval.objects.create(
            execution=execution,
            step="review",
            status=ApprovalStatus.APPROVED,
            approver=user,
            mode="ALL",
            order=0,
        )
        event = WorkflowEvent.objects.create(
            execution=execution,
            event_type="transition_executed",
            action="submit",
            source_state="draft",
            target_state="review",
            user=user,
        )
        comment = WorkflowComment.objects.create(
            execution=execution,
            text="please attach the quote",
            user=user,
        )

        ids = {
            "version": version.pk,
            "execution": execution.pk,
            "approval": approval.pk,
            "event": event.pk,
            "comment": comment.pk,
        }

        # 3. Upgrade to the current schema.
        executor = _fresh_executor()
        _migrate(executor, CURRENT_LEAF)
        assert _current_leaf(executor) == CURRENT_LEAF

        # 4. Every object survives with the same identity and fields.
        version.refresh_from_db()
        assert version.status == "PUBLISHED"
        assert version.definition["name"] == "upgrade_flow"

        execution.refresh_from_db()
        assert execution.workflow_name == "upgrade_flow"
        assert execution.current_state == "review"
        assert execution.workflow_version_id == ids["version"]

        approval.refresh_from_db()
        assert approval.status == ApprovalStatus.APPROVED
        assert approval.approver_id == user.pk

        event.refresh_from_db()
        assert event.action == "submit"
        assert event.event_type == "transition_executed"

        comment.refresh_from_db()
        assert comment.text == "please attach the quote"

        # 5. Analytics computed after the upgrade match the preserved data.
        metrics = execution_metrics(workflow="upgrade_flow")
        assert metrics.started == 1
        assert metrics.completed == 0
        assert metrics.rejected == 0

        # 6. The upgrade operated on the real data, not re-created records.
        assert WorkflowExecution.objects.count() == 1
        assert WorkflowVersion.objects.count() == 1
        assert Approval.objects.count() == 1
        assert WorkflowEvent.objects.count() == 1
        assert WorkflowComment.objects.count() == 1
    finally:
        _migrate(MigrationExecutor(connection), CURRENT_LEAF)


@pytest.mark.django_db(transaction=True)
def test_upgrade_keeps_new_indexes_usable(django_user_model):
    """The Phase 13 indexes are real and answer the documented access patterns."""
    connection = connections["default"]
    try:
        executor = MigrationExecutor(connection)
        _migrate(executor, PHASE13_LEAF)

        user = django_user_model.objects.create_user(username="upgrade_carol", password="pw")
        content_type = ContentType.objects.get_for_model(User)
        WorkflowExecution.objects.create(
            workflow_name="upgrade_flow",
            content_type=content_type,
            object_id=7,
            current_state="draft",
        )
        WorkflowExecution.objects.create(
            workflow_name="upgrade_flow",
            content_type=content_type,
            object_id=8,
            current_state="review",
        )
        assert user.pk is not None

        # The analytics ``state`` filter and the default ``-started_at`` ordering
        # both hit the newly created indexes without error.
        assert execution_metrics(state="draft").started == 1
        assert execution_metrics(state="review").started == 1
        assert list(WorkflowExecution.objects.order_by("-started_at")).__len__() == 2
    finally:
        _migrate(MigrationExecutor(connection), CURRENT_LEAF)


@pytest.mark.django_db
def test_migration_graph_has_no_duplicate_leaves():
    """The workflow_kit migration graph has exactly one latest leaf."""
    connection = connections["default"]
    graph = migrations.loader.MigrationLoader(connection).graph
    leaves = [key for key in graph.leaf_nodes() if key[0] == "workflow_kit"]
    assert leaves == [("workflow_kit", CURRENT_LEAF)]
