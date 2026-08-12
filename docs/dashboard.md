# Workflow Dashboard

The dashboard is a server-rendered Django application included with
`django-workflow-kit` (no frontend framework, no JavaScript build step). It is
a *consumer* of the existing engine, analytics and service layers — it never
duplicates a calculation or an authorization decision, so the numbers on screen
always agree with the REST analytics API and the backend engine remains the
source of truth.

## Installation

Add the app to `INSTALLED_APPS` and include its URLconf:

```python
INSTALLED_APPS = [
    ...
    "workflow_kit",
    "workflow_kit.dashboard",
    ...
]
```

```python
from django.urls import include, path

urlpatterns = [
    ...
    path("dashboard/", include("workflow_kit.dashboard.urls")),
]
```

## Pages

| Page | URL | Content |
| --- | --- | --- |
| Overview | `/dashboard/` | Headline metrics (active, completed, pending actions, SLA breaches, escalations, failed) plus a per-workflow health table (active, completion rate, SLA rate). |
| My Work | `/dashboard/my-work/` | The pending approvals the current user may decide (from the persisted `Approval` assignment records) and active delegations granted to them. |
| Executions | `/dashboard/executions/` | Searchable (workflow / state / id), filterable (workflow, state, version, status) and paginated execution listing. |
| Execution detail | `/dashboard/executions/<id>/` | State, pinned version, approvals, version history, timeline, comments, attachments and the append-only audit trail. |
| Analytics | `/dashboard/analytics/` | Execution metrics, completion, state durations, bottlenecks, approval metrics, SLA compliance, escalations and per-version analytics. |

## Permissions

Every page requires an authenticated user (`LoginRequiredMixin`).

Aggregate analytics (Overview and Analytics) follow the **same rule as the REST
analytics endpoints**: staff members or users holding the
`workflow_kit.view_analytics` permission. Users without it still see the
Overview — a permission notice plus their own pending actions, never the
aggregate metrics — and the Analytics page denies access entirely.

Execution-level pages never leak data: My Work derives its list from the same
assignment records the engine uses to authorize decisions, so a user only ever
sees the work they are genuinely allowed to decide.

`workflow_kit.view_analytics` is created by the package migrations on the
`WorkflowExecution` model. Grant it through Django's normal user/group
permission tools.

## Design system

The dashboard ships one plain CSS file
(`workflow_kit/dashboard/static/workflow_kit/dashboard/dashboard.css`) defining
design tokens (colour, spacing, radius, typography), components (cards, tables,
badges, buttons, inputs, panels, empty states) and responsive breakpoints. It
follows a `prefers-reduced-motion` media query, exposes a skip-to-content link,
labels navigation landmarks and uses `aria-current` for the active page, so
keyboard users and assistive technology get a fully usable experience.
