# Upgrading

This page records the migration path from earlier versions of
`django-workflow-kit`. The package uses Django migrations; upgrading is
normally a matter of installing the new version and running:

```bash
python manage.py migrate
```

## Migrations shipped by the package

| Migration | Adds / changes |
| --- | --- |
| `0001_initial` | `WorkflowExecution` with generic object reference. |
| `0002` | `Approval` and `WorkflowEvent` (append-only audit). |
| `0003` | Approval assignment / `allow_self` fields. |
| `0004` | `WorkflowVersion` + version pinning on executions; data migration backfills version 1 for pre-existing executions. |
| `0005` | `WorkflowComment` and `WorkflowAttachment`. |
| `0006` | Indexes on `WorkflowExecution.current_state` and `-started_at` (Phase 13 performance). |
| `0007` | Provisions the `workflow_kit.view_analytics` permission on `WorkflowExecution`. |

## Phase 13 migration verification

The Phase 13 migration tests (`tests/test_phase13_migrations.py`, 4 tests,
run against a real database) verify the upgrade path end to end:

- migration `0006` is **reversible** — the indexes can be dropped and re-added
  cleanly;
- Phase 12 data and analytics survive the upgrade;
- the new indexes are actually usable;
- the migration graph has a single leaf (no divergent history).

Note that after a reverse migration a fresh `MigrationExecutor` is required
before re-applying forward, and `executor.recorder` (not
`connections["default"]`) is the correct way to inspect recorded migrations.

## Upgrading pre-0.4 data

If you are upgrading a database that already contains executions created before
workflow versioning (Phase 9), migration `0004` pins them to a newly created
version 1 snapshot of the registered workflow. If a pre-existing definition
cannot be serialized (for example it uses dynamic conditions or callables that
are not JSON-safe), the data migration refuses to invent history and raises,
so the definition must be made serializable first.

## Compatibility

- Supported: Python >= 3.12, Django >= 6.1.
- The release matrix tests Python 3.12, 3.13 and 3.14 against Django 6.1 and
  6.2. SQLite is covered in CI; PostgreSQL is expected to work through the
  Django ORM but is not yet CI-tested.
- The REST API is optional (`django-workflow-kit[drf]`); the core package and
  the dashboard work without DRF.
- The clean-install test in the release gates installs the built wheel into a
  fresh environment and runs workflow, execution, transition, approvals, REST,
  admin, analytics and dashboard against it.
