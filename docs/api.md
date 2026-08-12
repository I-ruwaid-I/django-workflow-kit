# REST API

Django Workflow Kit ships an optional Django REST Framework integration. It is
a thin HTTP layer over the engine's Python API — authentication, permissions,
conditions, approvals, audit and timeline are all executed by the package
itself, never re-implemented in the API layer.

The API is **not** a core dependency: DRF only needs to be installed to use it,
and the rest of the package works without it.

## Installation

Install the package with the DRF extra:

```bash
pip install django-workflow-kit[drf]
```

or add `djangorestframework` to your own requirements.

## Setup

1. Add both apps to `INSTALLED_APPS`:

   ```python
   INSTALLED_APPS = [
       ...
       "rest_framework",
       "workflow_kit",
   ]
   ```

2. Include the API router in your root `urls.py`:

   ```python
   from django.urls import include, path

   urlpatterns = [
       ...
       path("api/", include("workflow_kit.api.urls")),
   ]
   ```

3. Configure DRF to use the package's error handler and pagination so errors
   and lists behave consistently:

   ```python
   REST_FRAMEWORK = {
       "DEFAULT_AUTHENTICATION_CLASSES": [
           "rest_framework.authentication.SessionAuthentication",
       ],
       "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
       "DEFAULT_PAGINATION_CLASS": "workflow_kit.api.pagination.WorkflowKitPagination",
       "EXCEPTION_HANDLER": "workflow_kit.api.exceptions.workflow_error_handler",
   }
   ```

   Only the exception handler is *required* for correct error mapping; the
   pagination class sets the default page size (20) used by the list endpoint.

## Authentication

The API ships with `IsAuthenticated` on every endpoint. Anonymous requests
receive the standard DRF `401`/`403` response. The demo project uses session
authentication; you can add any other DRF authentication class in your
`REST_FRAMEWORK` settings (e.g. token or JWT) — the workflow code does not care
how the caller was authenticated, only that a Django user is resolved.

## Endpoints

All endpoints operate on **workflow executions** (not the business objects
themselves). The current implementation exposes a single `executions` resource
with the following routes:

```text
GET    /api/executions/                 list (filterable, paginated)
GET    /api/executions/{id}/            detail (includes available_actions)
GET    /api/executions/{id}/actions/    actions available to the caller
POST   /api/executions/{id}/transition/ execute a transition
GET    /api/executions/{id}/history/    structured audit events
GET    /api/executions/{id}/timeline/   human-readable timeline
GET    /api/executions/{id}/approvals/  approval steps and decisions
POST   /api/executions/{id}/delegate/   delegate an approval slot to another user
POST   /api/executions/{id}/escalate/   reroute the current step to one escalation approver
GET    /api/executions/{id}/comments/   list comments on the execution
POST   /api/executions/{id}/comments/   attach a comment (JSON: {"text": "..."})
GET    /api/executions/{id}/attachments/    list attachments
POST   /api/executions/{id}/attachments/    upload a file (multipart form-data)
```

All routes are read-only except `transition`, `delegate`, `escalate`,
`comments` (POST) and `attachments` (POST).

### List — `GET /api/executions/`

Compact representations of the executions, newest first. The response uses
DRF's limit/offset `next`/`previous` style pagination:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 3,
      "workflow": "invoice_approval",
      "current_state": "manager_review",
      "state_label": "Manager Review",
      "is_completed": false,
      "object": {"type": "invoices.invoice", "id": 1},
      "started_at": "2026-01-01T10:00:00Z",
      "updated_at": "2026-01-01T10:05:00Z",
      "completed_at": null
    }
  ]
}
```

Supported query filters:

- `workflow=<name>` — only executions of that workflow definition.
- `current_state=<state>` — only executions in that state.
- `completed=<true|false>` — only finished (or still-running) executions.
- `page_size=<n>` — override the page size (max 100).

### Execution detail

`GET /api/executions/{id}/` returns the same fields plus
`available_actions`, computed for the calling user via the engine's own
permission and condition evaluation:

```json
{
  "id": 3,
  "workflow": "invoice_approval",
  "current_state": "manager_review",
  "state_label": "Manager Review",
  "is_completed": false,
  "object": {"type": "invoices.invoice", "id": 1},
  "started_at": "2026-01-01T10:00:00Z",
  "updated_at": "2026-01-01T10:05:00Z",
  "completed_at": null,
  "available_actions": [
    {"name": "approve", "label": "Approve"},
    {"name": "reject", "label": "Reject"}
  ]
}
```

### Actions

`GET /api/executions/{id}/actions/` returns the actions the *current*
caller may execute, again resolved by the engine:

```json
{"actions": [{"name": "approve", "label": "Approve"}, {"name": "reject", "label": "Reject"}]}
```

Actions hidden by permission or by a failing condition are excluded — both here
and from `available_actions` on the detail endpoint.

### Transition

`POST /api/executions/{id}/transition/` executes an action on behalf of the
authenticated user:

```json
{"action": "approve", "reason": "Quotation attached"}
```

`reason` is optional. On success the response describes the applied change:

```json
{
  "id": 3,
  "action": "approve",
  "previous_state": "manager_review",
  "current_state": "finance_review",
  "is_completed": false
}
```

`approve` and `reject` route through the approval-service **decision** methods
(so each completed "review" step also records an Approval decision); every
other action name goes through the generic transition API.

### History, timeline, approvals

`GET /api/executions/{id}/history/` returns the structured, append-only audit
events:

```json
[
  {
    "event": "workflow_started",
    "actor": null,
    "timestamp": "2026-01-01T10:00:00Z",
    "source_state": null,
    "target_state": "draft",
    "action": null,
    "reason": null,
    "metadata": {}
  }
]
```

`GET /api/executions/{id}/timeline/` returns the derived, human-readable
timeline entries (`label`, `actor`, `timestamp`, source/target state, action,
reason, metadata).

`GET /api/executions/{id}/approvals/` returns the approval steps and decisions
for the execution (`step`, `status`, `mode`, `order`, `assignment`, `action`,
`reason`, `approver`, `due_at`, `is_overdue`, `created_at`, `updated_at`).

### Delegation and escalation

`POST /api/executions/{id}/delegate/` forwards an approver's slot to another
user (username required):

```json
{"grantee": "payables_lead", "step": "finance_review", "reason": "On leave"}
```

On success the delegation is returned; the grantee can then decide the step
and the engine authorizes the decision against the granter's rights.

`POST /api/executions/{id}/escalate/` reroutes the current step to a single
escalation approver:

```json
{"approver": "Executive", "reason": "Urgent override"}
```

The step's pending approvals are cancelled and replaced by one any-of approval
the escalation approver alone decides; that approval is returned. See
[`approvals.md`](approvals.md) for the underlying semantics.

### Comments and attachments

`GET /api/executions/{id}/comments/` lists the execution's comments, oldest
first; each entry exposes `id`, `text`, `author` and `created_at`:

```json
[
  {
    "id": 4,
    "text": "Please attach the quotation.",
    "author": "alice",
    "created_at": "2026-01-02T09:00:00Z"
  }
]
```

`POST /api/executions/{id}/comments/` attaches a comment (the caller is
recorded as the author) and returns the created comment with `201`:

```json
{"text": "Quotation attached."}
```

`GET /api/executions/{id}/attachments/` lists the execution's attachments
(`id`, `name`, `content_type`, `size`, `extension`, `url`, `created_at`).
`POST /api/executions/{id}/attachments/` uploads a file via multipart
form-data; the `file` field is required and `name` optionally overrides the
stored display name. The upload is written through Django's default storage
backend and the created attachment is returned with `201`.

Adding a comment or uploading an attachment appends the corresponding audit
event (`comment_added` / `attachment_added`) and emits the matching domain
event, so the discussion and files appear in the execution's history, timeline
and event stream exactly like state changes — see [Comments](comments.md) and
[Attachments](attachments.md).

## Error handling

Engine exceptions are mapped to stable, structured JSON. Python stack traces
are never exposed to clients.

| HTTP status | `error` code            | When                                        |
| ----------- | ----------------------- | ------------------------------------------- |
| 400         | *(DRF serializer)*      | missing/invalid request body                |
| 403         | `permission_denied`     | caller may not perform the action           |
| 404         | —                       | execution not found / object hidden         |
| 409         | `invalid_transition`    | action invalid from the current state       |
| 409         | `workflow_completed`    | the workflow is already complete            |
| 409         | `approval_not_pending`  | approving/rejecting a step that is not pending |
| 422         | `condition_failed`      | a condition blocked the transition          |

Response shape:

```json
{"error": "invalid_transition", "message": "Cannot perform 'approve' from state 'draft'."}
```

Unknown exceptions fall through to DRF's default handler, so standard
authentication and permission failures keep their normal DRF representation.

## Security guarantees

- The API never serializes arbitrary business-object fields. Objects are
  rendered only as `{"type": "<app_label>.<model>", "id": <pk>}`.
- Authorization, conditions and action resolution come from the engine �?" there
  is no second permission check the API could get wrong.
- The caller cannot execute an action the actions endpoint hides from them.

## Analytics

Read-only aggregate analytics are exposed under `/api/analytics/`. All
endpoints are `GET`, accept the shared scope query parameters (`workflow`,
`version`, `start`, `end`, with `state`/`step` where meaningful) and are gated
by `IsAnalyticsViewer`: authenticated staff members, or users holding the
`workflow_kit.view_analytics` permission.

| Endpoint                          | Returns                                                            |
| --------------------------------- | ------------------------------------------------------------------ |
| `/api/analytics/metrics/`         | execution counts (started/active/completed/rejected/cancelled/...). |
| `/api/analytics/completion/`      | completion-time statistics in seconds.                             |
| `/api/analytics/state_duration/`  | per-state turnaround durations.                                    |
| `/api/analytics/bottlenecks/`     | state durations ranked by average, `is_bottleneck` flags.          |
| `/api/analytics/approvals/`       | approval counts and decision-time statistics.                      |
| `/api/analytics/approval_totals/` | approval counts grouped by `group_by` (default `workflow`).        |
| `/api/analytics/sla/`             | SLA compliance, breaches, overdue and completion statistics.       |
| `/api/analytics/escalations/`     | escalation distribution by workflow/state/reason.                  |
| `/api/analytics/versions/`        | per-version execution analytics.                                   |

`AnalyticsError` (bad date, non-integer version, unknown grouping) maps to
HTTP 400 with `{"error": "invalid_analytics_arguments"}`. See the
[Analytics](analytics.md) guide for the underlying Python API.

`workflow_kit.view_analytics` is created by the package migrations on the
`WorkflowExecution` model. Grant it through Django's normal user/group
permission tools.

## Demo

The `examples/invoice_approval` project mounts the API at `/api/` (session
authentication; log in at `/accounts/login/` first). Its REST test suite
(`invoices/tests/test_rest_api.py`) walks all six endpoints end to end,
including an unauthorized transition.
