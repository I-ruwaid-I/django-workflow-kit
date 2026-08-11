# Analytics

Phase 12 adds a read-only analytics layer that turns the data the workflow
engine already produces — executions, approvals, the append-only audit trail,
events and versions — into operational information. Analytics never write to
the database and never run a second engine: every number derives from the
existing tables through the normal ORM.

The public API lives in `workflow_kit.analytics`:

| What it answers            | Entry points                                            |
| -------------------------- | ------------------------------------------------------- |
| What is happening          | `execution_metrics`, `version_analytics`                |
| How long it takes          | `completion_metrics`, `state_durations`, `bottlenecks`  |
| Where approvals slow down  | `approval_metrics`, `approval_totals`                   |
| How SLAs are met           | `sla_metrics`, `escalation_analytics`                   |
| How to scrape it           | `prometheus_metrics_text`, `collect_metrics`            |

All querying functions share the same scope parameters:

- `workflow` — restrict to one workflow by name;
- `workflow_version` — restrict to a definition version number;
- `start` / `end` — a timezone-aware range (ISO strings accepted);
- `state` — for execution queries the current state; for approval queries the
  approval step name.

Invalid arguments (an unparsable date, a non-integer version, an unknown
grouping) raise `workflow_kit.analytics.AnalyticsError`, a `ValueError`
subclass. Dates without a timezone are interpreted in the current Django time
zone.

## Execution metrics

```python
from workflow_kit.analytics import execution_metrics

metrics = execution_metrics(workflow="invoice_approval")
print(metrics.started, metrics.active, metrics.completed)
print(metrics.to_dict())   # JSON-safe
print(metrics.summary())   # human-readable one-liner
```

Counts returned: `started`, `active`, `completed`, `rejected`, `cancelled`,
`failed`, `escalated` and `sla_breached`.

Outcome classification uses the audit trail. The engine records every terminal
transition as a `workflow_completed` event whose `action` is the transition
name, so:

- `completed` = a `workflow_completed` event whose action is not `reject` or
  `cancel`;
- `rejected` = an `approval_rejected` event or a `reject` transition;
- `cancelled` = a `cancel` transition (or an explicit `workflow_cancelled`
  event);
- `failed` = reached a terminal state without any of the markers above;
- `escalated` = an `approval_escalated` event;
- `sla_breached` = an approval that is still overdue while pending, or was
  decided after its `due_at` deadline.

Counts use database aggregations and `Exists` subqueries, so their query cost
is constant regardless of how many executions are in scope. `version_analytics`
reports each persisted `WorkflowVersion` once with its own metrics and average
completion time.

## Duration and turnaround

```python
from workflow_kit.analytics import completion_metrics, state_durations, bottlenecks

completion = completion_metrics(workflow="invoice_approval")
# completion.total, completion.completed, completion.duration (seconds)

for row in state_durations(workflow="invoice_approval", start="2024-01-01", end="2024-06-30"):
    print(row.state, row.count, row.duration.average)

for row in bottlenecks(workflow="invoice_approval", threshold=1.25):
    if row.is_bottleneck:
        print("stall:", row.state)
```

`DurationStats` summarises durations in seconds: `count`, `average`, `median`,
`minimum`, `maximum`, `p95` and `p99`. `state_durations` reconstructs how long
executions spend in each state from the `started_at` timestamp, the ordered
`transition_executed` audit events and `completed_at` (running executions count
up to "now"). `bottlenecks` flags the states whose average duration exceeds the
overall average by `threshold` times — it identifies *where* workflows stall
without claiming a cause.

## Approval analytics

```python
from workflow_kit.analytics import approval_metrics, approval_totals

metrics = approval_metrics(workflow="invoice_approval")
# requested, approved, rejected, pending, cancelled, escalated, sla_breached,
# approved_duration, rejected_duration

for row in approval_totals(workflow="invoice_approval", group_by="step"):
    print(row)
```

`approval_totals` groups the counts with a single aggregation by `workflow`,
`version`, `step`, `approver` or `status`.

## SLA and escalations

```python
from workflow_kit.analytics import sla_metrics, escalation_analytics

sla = sla_metrics(workflow="invoice_approval")
# tracked, decided, on_time, breached, pending_overdue, compliance_rate,
# average_overdue, escalation_count, average_completion_time

escalations = escalation_analytics(workflow="invoice_approval")
# total, by_workflow, by_state, by_reason, average_delay_seconds
```

`compliance_rate` is `on_time / decided * 100` (`None` when nothing has been
decided). Escalation breakdowns are derived from the `approval_escalated`
audit events — no separate escalation table is consulted.

## Prometheus

`prometheus_metrics_text` renders the same aggregates as Prometheus text format
without requiring `prometheus_client`:

```python
from workflow_kit.analytics import prometheus_metrics_text

exposition = prometheus_metrics_text(workflow="invoice_approval")
```

Metrics exposed include `workflow_executions_started_total`,
`workflow_executions_active`, `workflow_executions_completed_total`,
`workflow_execution_completion_duration_seconds` (summary),
`workflow_approval_*` counters, `workflow_sla_compliance_ratio` and
`workflow_sla_breaches_total`. Labels use only low-cardinality values such as
the workflow name. `collect_metrics` returns the numbers as a plain nested
dict if you prefer to feed them into `prometheus_client` yourself.

## HTTP and admin access

The same analytics are available as read-only REST endpoints under
`/api/analytics/` (see [REST API](api.md#analytics)) and as an admin summary
page on the execution admin (see [Django Admin](admin.md#analytics-summary)).
Both are authorization-gated.

## Performance notes

- Counts are computed on the database; only the small timestamp/status columns
  needed for duration statistics are materialised in Python.
- `version_analytics` and the admin summary are bound by the *number of
  versions / workflows*, never by execution volume.
- State-duration analysis loads one timestamp/value row per execution plus the
  `transition_executed` events of those executions — two queries in total.