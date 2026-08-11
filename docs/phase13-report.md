# Phase 13 — Completion Report

## Production Hardening

- **Concurrency:** `engine.versioning.ensure_workflow_version` runs inside
  `transaction.atomic()` with an `IntegrityError` fallback, so parallel first
  use deterministically collapses to a single v1. Approval decisions and
  version publishes already row-lock (`select_for_update`). 16 deterministic
  concurrency/idempotency tests (`tests/test_phase13_concurrency.py`).
- **Performance:** execution list uses
  `select_related("content_type", "workflow_version")`; query-count regression
  tests cap queries for list / detail+actions / history+timeline / analytics;
  migration `0006` adds justified indexes on `WorkflowExecution.current_state`
  and `-started_at`.
- **Security:** `AttachmentError` added; upload size
  (`ATTACHMENT_MAX_SIZE`), content-type allow-list
  (`ATTACHMENT_ALLOWED_CONTENT_TYPES`), path-traversal-resistant file names,
  and opt-in public attachment URLs (`ATTACHMENT_PUBLIC_URLS`). 15 security
  tests covering API authorization, tenant/object isolation, logging/webhook
  hygiene, admin read-only and version immutability.
- **Migrations:** migration `0006` is reversible; migration tests run real DDL
  and verify Phase 12 data/analytics survive, indexes are usable, and the graph
  has a single leaf.
- **API stability:** removed the never-bound `Approval` / `ApprovalStatus`
  ORM names from the top-level `__all__` (ORM models live under
  `workflow_kit.models`; core still imports without Django apps loaded). 8 API
  surface tests.
- **Compatibility:** package and demo suites run independently; demo carries
  its own `pytest.ini` and now mounts the dashboard.
- **Dependencies:** core remains Python + Django only; DRF optional
  (`[drf]` extra); no Celery/Redis/frontend dependency. Verified by the
  clean-install test (§73): wheel installed into a fresh venv, fresh Django
  project, full end-to-end run.

## Workflow Dashboard

- **Architecture:** `workflow_kit.dashboard` — plain Django (templates +
  static CSS), no frontend framework; consumes the engine/analytics/service
  layers, never a second source of truth.
- **Pages:** Overview (metrics + per-workflow health), My Work (assignable
  pending approvals + active delegations), Executions (search/filter/
  paginate), Execution detail (state, version, approvals, timeline, comments,
  attachments, audit), Analytics (metrics, completion, state durations,
  bottlenecks, approvals, SLA, escalations, versions).
- **API integration:** re-uses the same analytics functions the REST API
  wraps and the same `IsAnalyticsViewer` rule.
- **Permissions:** `LoginRequiredMixin` everywhere; aggregate screens require
  staff or `workflow_kit.view_analytics`; Overview redirects non-viewers to
  My Work; execution data derived from persisted approval assignments.
- **Accessibility:** skip link, landmark nav, `aria-current`, labelled forms,
  visible focus, `prefers-reduced-motion`.
- **Responsive:** grid/panel layouts collapse below 760px; touch-friendly
  spacing.
- **Performance:** `select_related` on My Work and execution detail; single
  aggregate queries reused from analytics.

## Tests

- **Package tests:** 515 passed (Phase 13 added 63: 16 concurrency, 5
  query-count, 15 security, 4 migrations, 8 API surface, 15 dashboard).
- **Demo tests:** 66 passed (includes 6 dashboard tests mounted at
  `/dashboard/`).
- **Dashboard tests:** 15 (package) + 6 (demo).
- **Concurrency tests:** 16.
- **Security tests:** 15.
- **Performance tests:** 5 query-count + `test_many_executions_stay_fast`.

## Quality Gates

- **Coverage:** 91.05% (required ≥ 90%).
- **Ruff:** `ruff check .` passed.
- **Ruff format:** `ruff format --check .` passed (165 files).
- **MyPy:** passed, 90 source files.
- **Build:** `python -m build` produced sdist + wheel.
- **Twine:** `twine check dist/*` PASSED for wheel and sdist.
- **Migration check:** `makemigrations --check` — no changes detected.

## Package

- **Version:** 0.4.0 (unchanged; hardening + dashboard added without a minor
  bump per phase policy).
- **Wheel:** `django_workflow_kit-0.4.0-py3-none-any.whl`.
- **SDist:** `django_workflow_kit-0.4.0.tar.gz`.

## Documentation

- **Updated files:** `README.md`, `docs/index.md`, `CHANGELOG.md`,
  `examples/invoice_approval/FEATURE_COVERAGE.md`, and the demo README.
- **New files:** `docs/dashboard.md`, `docs/production.md`,
  `docs/security.md`, `docs/performance.md`, `docs/upgrade.md`, and this
  report.

## Known limitations

- The dashboard is read-only by design (decisions go through the engine/API).
- Webhook integration is configured (not queued); no Celery/Redis background
  execution.
- Attachment `url` exposure is opt-in (`ATTACHMENT_PUBLIC_URLS`); by default
  no storage URL is disclosed.

## Breaking changes

- None. `workflow_kit.__all__` no longer lists `Approval` / `ApprovalStatus`
  (they were never bound at import time, so no working import relied on them).

## Recommended 1.0 actions

- Bump to `1.0.0` after a deliberate release pass (Phase 14), then publish to
  TestPyPI followed by PyPI.
- Consider a separate workflow-designer (drag-and-drop) package rather than a
  core dependency.
- Add optional Celery execution as an opt-in integration, not a requirement.
