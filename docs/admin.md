# Django Admin

*(Implemented in Phase 1 for executions; extended in Phase 4.)*

`django-workflow-kit` registers read-only admin views so operators can inspect
workflow executions, approvals and the audit trail without risking state
changes outside the engine.

## Registered views

| Model            | Purpose                                        |
| ---------------- | ---------------------------------------------- |
| `WorkflowExecution` | A running workflow instance and its state   |
| `Approval`       | Approval requirements and their decisions      |
| `WorkflowEvent`  | The append-only audit trail                    |

All three are configured with:

- useful `list_display` columns and `list_filter` /
  `search_fields` for finding records;
- `readonly_fields` for every persisted field;
- `has_add_permission`, `has_change_permission` and `has_delete_permission`
  all returning `False`.

This means admin users can view executions, approvals and history, but can
never create, edit or delete records through the admin. Workflow decisions are
made exclusively through the public engine API
(`execution.transition()`, `execution.approve()`, `execution.reject()`), which
enforces authorization and conditions.

## Setup

The admin module is registered through Django's autodiscovery when
`django.contrib.admin` is in `INSTALLED_APPS` together with `workflow_kit`:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    # ...
    "workflow_kit",
]
```

No further configuration is required.

## Analytics summary

The workflow-execution changelist admin also exposes a read-only analytics
summary page at
`/admin/workflow_kit/workflowexecution/summary/`, listing per-workflow
aggregate counts (started, active, completed, rejected, cancelled, failed,
escalated, SLA-breached) and the average completion time for every workflow
that has at least one execution.

The page is served through the admin site's own view wrapper, so the usual
staff/superuser rules apply, and it only ever reads the database. The counts
come from the same `workflow_kit.analytics` layer documented in
[Analytics](analytics.md).