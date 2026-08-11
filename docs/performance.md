# Performance

The package is designed to keep database work bounded as execution volumes
grow. This page documents the techniques in place and the regression tests
that protect them.

## Query discipline

- **Select related** — the REST execution list loads `content_type` and
  `workflow_version` through `select_related`, removing an N+1 for versioned
  listings (`workflow_kit/api/views.py::get_queryset`).
- **Aggregations over materialization** — analytics counts use database
  aggregations and `Exists` subqueries rather than pulling rows into Python.
  `test_many_executions_stay_fast` verifies the metrics query stays at a
  constant cost regardless of execution volume.
- **Duration stats with a single pass** — only the small columns required for
  duration statistics are loaded from the audit trail.

## Indexes

Migration `0006` adds justified indexes on `WorkflowExecution` for the common
access patterns:

- `current_state` — state-filtered listings (dashboard and API).
- `-started_at` — recent-first ordering.

Every other indexed column in the package was introduced with its migration and
is exercised by the query-count regression tests.

## Query-count regression tests

`tests/test_phase13_queries.py` caps the number of SQL queries for the hot
paths, so a future change that reintroduces an N+1 fails loudly:

- execution list
- execution detail + available actions
- history / timeline
- analytics metrics

## Dashboard

The dashboard reuses the same analytics functions as the REST API (no
duplicate calculation) and uses `select_related` for execution detail and My
Work lookups. It is server-rendered plain Django, so there is no client-side
data fetching to pay for.

## Measured behaviour

See the Phase 12 analytics docs for the duration statistics the engine can
report (`docs/analytics.md`), which double as a way to profile turnaround per
state in production.
