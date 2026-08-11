# Production Hardening

Phase 13 focuses on making the engine safe to run in production: deterministic
concurrency, bounded query performance, a reviewed security posture, verified
migrations and a stable public API.

## Concurrency

`engine.versioning.ensure_workflow_version` creates a workflow's first version
inside `transaction.atomic()` and retries on the unique constraint when two
processes race, so parallel first use always collapses to a single version 1.
Execution state changes and approval decisions already re-read and row-lock the
execution (`select_for_update`) inside one transaction, and version publishing
is row-locked too. See the concurrency tests in
`tests/test_phase13_concurrency.py` (16 deterministic tests).

## Database and query performance

- The execution list API uses `select_related("content_type", "workflow_version")`
  to remove an N+1 for versioned listings.
- Query-count regression tests (`tests/test_phase13_queries.py`) cap the number
  of queries for list, detail + actions, history/timeline and analytics screens.
- Migration `0006` adds justified indexes on `WorkflowExecution.current_state`
  and `-started_at` for the common state-filter and recent-first orderings.

## Migrations and upgrades

Migration `0006` is reversible, and the migration tests
(`tests/test_phase13_migrations.py`) verify a real upgrade path: Phase 12 data
and analytics survive, the new indexes are usable, and the migration graph has
a single leaf. See [Upgrading](upgrade.md).

## API stability

`workflow_kit.__init__` exposes only the stable, intentional public surface.
The internal `Approval` / `ApprovalStatus` ORM classes were removed from the
top-level namespace — ORM models belong under `workflow_kit.models` because the
core package must import without Django apps being loaded (verified by the
`tests/test_no_drf.py` subprocess test). See
`tests/test_phase13_api_surface.py` (8 tests).

## Dependencies

The core package depends only on Python and Django. Everything else is
optional:

- **DRF** — `pip install django-workflow-kit[drf]` (REST API, optional).
- **Celery / Redis** — not required; work is executed synchronously.
- **Frontend** — the dashboard is plain Django templates + static CSS; no
  React/Vue and no JavaScript build tooling.
- **Metrics** — the Prometheus text exposition is dependency-free.

See the wheel contents and the [clean-install test](#clean-installation) below.

## Clean installation

A clean-environment test is part of the release gates: the built wheel is
installed into a fresh virtual environment, a brand-new Django project is
created, and workflow / execution / transition / approvals, the REST API, admin
registrations, analytics and the dashboard are all exercised against the
installed package (never the source tree).

## Compatibility

The test suite runs the package and the Invoice Approval demo independently.
The demo runs with its own `pytest.ini`, and the package suite pins its own
Django settings; both must pass before a release.
