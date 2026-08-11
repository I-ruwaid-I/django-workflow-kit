# Phase 12 — Observability and Analytics: Completion Report

**Status:** Implemented, tested, documented, and green across all quality gates.

## Scope

Phase 12 adds a read-only observability and analytics layer on top of the data
the engine already produces. It answers "what is happening", "how long is it
taking", "where do approvals slow things down" and "how often are SLAs
breached" — entirely derived from the existing executions, approvals, audit
trail, events and versions tables. In keeping with the procedural rule, it does
**not** introduce a second engine, approval, permission, condition, audit,
event, notification or versioning system: metrics reuse the normal ORM and the
Phase 5 event dispatcher.

## New modules

| Module | Purpose |
| ------ | ------- |
| `analytics/base.py` | `AnalyticsError`, aware-date parsing, the shared `execution_queryset` scope helper, `DurationStats` (count/average/median/min/max/P95/P99 in seconds) |
| `analytics/metrics.py` | `execution_metrics` aggregates (started, active, completed, rejected, cancelled, failed, escalated, SLA-breached) via DB aggregations and `Exists` subqueries; `version_analytics` per-version breakdowns |
| `analytics/duration.py` | `completion_metrics`, `state_durations` (per-state turnaround reconstructed from the audit trail) and `bottlenecks` |
| `analytics/approvals.py` | `approval_metrics` and `approval_totals` with decision-time statistics and grouping by workflow/version/step/approver/status |
| `analytics/sla.py` | `sla_metrics` (compliance rate, breaches, pending-overdue, average overdue) and `escalation_analytics` distributions |
| `analytics/prometheus.py` | dependency-free `prometheus_metrics_text` text exposition and `collect_metrics` dict form |
| `observability.py` | `correlation_id`/`set/reset_correlation_id` (contextvars) and `StructuredEventLogger` subscribed to the existing event dispatcher |
| `api/analytics_views.py` | `IsAnalyticsViewer` permission and the `WorkflowAnalyticsViewSet` REST endpoints |

## Outcome classification

The audit layer records every terminal transition as a `workflow_completed`
event whose `action` is the transition name, so metrics classify outcomes by
that action: `completed` (non-reject/cancel), `rejected` (approval-rejected or
`reject` transition), `cancelled` (`cancel` transition), `failed` (terminal
without any marker), plus `escalated` and `sla_breached` derived from
`approval_escalated` events and approval `due_at` deadlines.

## Performance

- Execution/approval counts are computed on the database; only the small
  timestamp columns needed for duration statistics are pulled into Python.
- `version_analytics` and the admin summary are bounded by the number of
  versions / workflows, never by execution volume.
- `state_durations` issues two queries total (one value-row set, one
  `transition_executed` set) regardless of dataset size. The query-count test
  pins the metrics path to a constant number of queries at 150 executions.

## HTTP and admin

- REST analytics endpoints under `/api/analytics/` (metrics, completion, state
  durations, bottlenecks, approvals, approval totals, SLA, escalations,
  versions), gated by `IsAnalyticsViewer` (authenticated staff, or holders of
  the `workflow_kit.view_analytics` permission).
- `AnalyticsError` maps to HTTP 400 with `{"error":
  "invalid_analytics_arguments"}` via the existing API exception handler.
- A read-only admin summary page at
  `/admin/workflow_kit/workflowexecution/summary/` renders per-workflow
  aggregates; it goes through the admin site's own staff wrapper and never
  writes to the database.

## Observability

`StructuredEventLogger` is installed automatically from `AppConfig.ready()`
(unless `WORKFLOW_KIT["STRUCTURED_LOGGING"]` is `False`) and logs every domain
event as a structured record whose `workflow_event` extra carries a
JSON-friendly payload including any active correlation id. `correlation_id` is
`contextvars`-backed, so nested scopes restore naturally and per-request
correlation across logs, notifications and webhooks is straightforward.

## Deliverables

- New analytics and observability code (above) — version bumped to **0.4.0**.
- Tests: `tests/test_analytics_{metrics,duration,approvals,sla,prometheus}.py`,
  `tests/test_observability.py`, `tests/test_analytics_api.py`,
  `tests/test_admin_summary.py`, plus the shared `tests/analytics_helpers.py`
  builders. **452 tests pass.**
- Docs: `docs/analytics.md`, `docs/observability.md`,
  `docs/phase12-report.md`; `docs/index.md`, `docs/api.md` and `docs/admin.md`
  updated with the analytics endpoints and summary page.
- Demo: `scripts/demo_smoke.py` extended with checks 18–24 exercising the
  analytics, Prometheus text and correlation-id observability against the live
  demo database; the invoice demo's `FEATURE_COVERAGE.md` matrix updated.

## Quality gates

| Gate | Result |
| ---- | ------ |
| `pytest -q` | 452 passed |
| `ruff check .` | clean |
| `ruff format --check .` | clean (153 files) |
| `mypy workflow_kit` | no issues (84 files) |
| `compileall -q workflow_kit` | clean |
| bare `import workflow_kit` (no Django configured) | works, `0.4.0` |
| `scripts/demo_smoke.py` | completes through check 24 |