# Invoice Approval Demo

A standalone Django application that dogfoods **django-workflow-kit** exactly
like an external developer would: through the package's public API only.

The demo is permanent. It evolves alongside the package and is kept working at
all times. It is the integration test surface and the reference example for
how a real Django project uses the library.

```
              django-workflow-kit
                      ▲
                      │ public API
                      │
              Invoice Approval Demo
```

## What it demonstrates

- A conventional Django project with the package installed
  (`workflow_kit` in `INSTALLED_APPS`)
- Django session login (`/accounts/login/` + logout) using the seeded accounts
- An `Invoice` model whose workflow state lives in a
  `WorkflowExecution` (no `status` field on the model)
- An `Invoice` workflow defined through the package's public API
  (`invoices/workflow.py`)
- Engine-enforced authorization: submit requires the `Employee` group, the
  manager review stage requires `Manager`/`invoices.can_reject_invoice`, and
  the final approval requires `invoices.can_finalize_invoice` (see the
  permission matrix below)
- Basic list / create / detail views, workflow action views and templates
- The invoice approval workflow with conditional routing by amount:

```
Draft ── Submit ──> Manager Review ── Approve ──> Finance Review ── Approve ──> Approved
                        │                                │                           │
                     Reject                          Reject          amount > 10 000 │
                        │                                │                      Approve
                        ▼                                ▼                           ▼
                     Rejected                          Rejected             Executive Review
                                                                                    │
                                                                                 Reject
                                                                                    ▼
                                                                                Rejected
```

Invoices up to `10_000` are finalized directly from Finance Review; larger
invoices are routed to an additional Executive Review step. The conditions
that drive this routing live on the transitions in `invoices/workflow.py` and
are re-evaluated against the live invoice at decision time.

Executive Review is a **parallel all-of** approval: `invoices/workflow.py`
declares an `ApprovalRequirement` that puts one approval in the hands of a
member of the `Executive` group and a second in the hands of a member of the
`Finance` group, and the execution only advances once *both* slots are decided.
The demo also exercises Phase 9 **delegation** (an approver forwards their slot
to a grantee) and **escalation** (a step is rerouted to a single escalation
approver) through `invoices/services.py`.

The demo also demonstrates Phase 9 **workflow versioning**. The definition is
built with `build_invoice_workflow(executive_threshold=...)`; the first invoice
creation publishes it as **version 1**, so every execution is pinned to a
numbered, immutable definition snapshot. `publish_invoice_v2` in
`invoices/services.py` publishes a **version 2** with a higher executive
threshold (25 000). New executions bind to version 2, while executions already
running keep the version — and therefore the routing rules — they started with
(see `test_publishing_v2_keeps_running_executions_on_v1`).

The demo also demonstrates Phase 10 **comments and attachments**. The invoice
detail page lets participants attach a comment or upload a file to the
execution (`invoices/services.py` → `add_invoice_comment` /
`attach_invoice_file`). Both are recorded in the audit trail (`comment_added` /
`attachment_added`), appear in the timeline, and are emitted as domain events,
just like state changes.

> **Status:** Phases 1–10 of the package are implemented and drive the demo
> lifecycle end-to-end: the core engine, permissions, sequential and parallel
> approvals, the audit trail and timeline, conditional routing by invoice
> amount, delegation, escalation, workflow versioning, comments and
> attachments, and the optional DRF REST API. Notifications are demonstrated on
> completion.

## Project structure

```text
examples/invoice_approval/
├── manage.py
├── config/          # Django project settings, urls, asgi, wsgi
├── invoices/        # The demo application
│   ├── workflow.py  # Invoice workflow definition (public Workflow API)
│   ├── models.py    # Invoice model + state-aware conveniences
│   ├── services.py  # Service layer (workflow actions land here)
│   ├── views.py     # Simple Django views
│   ├── forms.py
│   ├── admin.py
│   ├── urls.py
│   ├── management/commands/  # seed_demo_users
│   ├── migrations/
│   └── tests/
├── templates/
├── static/
├── requirements.txt
├── pytest.ini
└── FEATURE_COVERAGE.md
```

## Installation

Requires Python >= 3.12 and Django >= 6.1.

From the demo directory, install the local development version of the package
and the demo's runtime requirements:

```bash
cd examples/invoice_approval
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

The package is not copied into the demo; `requirements.txt` references it with
`-e ../..` (editable install from the repository root).

## Setup

```bash
python manage.py migrate
python manage.py seed_demo_users     # creates the demo accounts below
python manage.py createsuperuser     # optional, for the Django admin
```

### Demo accounts and permission matrix

`seed_demo_users` creates four accounts (password `demo-password-123`) with
these roles. The engine rejects any other user (including anonymous visitors)
and superusers bypass authorization on every transition.

| Username  | Groups    | Django permissions                 | Can do                                        |
| --------- | --------- | ---------------------------------- | --------------------------------------------- |
| `employee`| Employee  | —                                  | submit invoices                               |
| `manager` | Manager   | `invoices.can_reject_invoice`      | approve at Manager Review; reject any review  |
| `finance` | Finance   | `invoices.can_reject_invoice`, `invoices.can_finalize_invoice` | finalize or reject at Finance Review |
| `executive`| Executive | `invoices.can_reject_invoice`, `invoices.can_finalize_invoice` | finalize or reject at Executive Review |

The canonical permission catalog lives on the `Invoice` model
(`Meta.permissions`) and is referenced by `invoices/workflow.py`.

## Running the server

```bash
python manage.py runserver
```

Then open:

- Invoice list: <http://127.0.0.1:8000/invoices/>
- Create invoice: <http://127.0.0.1:8000/invoices/create/>
- Log in: <http://127.0.0.1:8000/accounts/login/>
- Admin: <http://127.0.0.1:8000/admin/>

The invoice list and create pages are public. Invoice detail and the
submit/approve/reject actions require a logged-in user; the engine then checks
that user's groups and permissions before applying an action, so e.g. an
`employee` cannot approve and a `manager` cannot finalize. Workflow views never
make this decision themselves — the same service layer and engine enforce it
for both the UI and any other caller.

## REST API

The demo also mounts the optional DRF-based workflow API at `/api/executions/`
(session authentication only; log in at `/accounts/login/` first). It exposes
the same engine underneath — `workflow_kit.api` is a thin HTTP layer over the
package's Python API, so authorization and conditions behave identically to the
web UI:

```text
GET  /api/executions/                      list (filterable, paginated)
GET  /api/executions/{id}/                 detail incl. available_actions
GET  /api/executions/{id}/actions/         actions available to the caller
POST /api/executions/{id}/transition/      execute a transition
GET  /api/executions/{id}/history/         structured audit events
GET  /api/executions/{id}/timeline/        human-readable timeline
GET  /api/executions/{id}/approvals/       approval steps/decisions
POST /api/executions/{id}/delegate/        delegate an approval slot to a user
POST /api/executions/{id}/escalate/        escalate the current step
GET  /api/executions/{id}/comments/        list comments
POST /api/executions/{id}/comments/        attach a comment
GET  /api/executions/{id}/attachments/     list attachments
POST /api/executions/{id}/attachments/     upload a file (multipart/form-data)
```

Engine errors map to structured JSON (`invalid_transition`, `permission_denied`,
`condition_failed`, `workflow_completed`, ...); Python stack traces are never
exposed. See [`docs/api.md`](../../docs/api.md) for the full reference.

## Workflow Dashboard

The demo also mounts the server-rendered Workflow Dashboard at
`/dashboard/` (`workflow_kit.dashboard`): an Overview with headline metrics and
per-workflow health, a My Work queue of the pending approvals the logged-in
user can decide, searchable/filterable/paginated executions with full detail
(state, version, approvals, timeline, comments, attachments, audit) and
permission-gated Analytics. Regular demo accounts land on My Work; staff (or
holders of `workflow_kit.view_analytics`) see aggregate analytics. See
[`docs/dashboard.md`](../../docs/dashboard.md).

## Running the tests

Install the repository development tooling (pytest, pytest-django):

```bash
pip install -e ../..[dev]
```

Then run the demo tests from the repository root or the demo directory:

```bash
pytest examples/invoice_approval/
```

or, inside the demo directory:

```bash
pytest
```

## Roadmap

| Phase | Demo additions |
| ----- | -------------- |
| 1 | Workflow definition via public API; submit/approve/reject actions |
| 2 | Permissions and groups (Employee, Manager, Finance) enforced by the engine; demo accounts |
| 3 | Sequential approvals and approval history |
| 4 | Audit trail, timeline |
| 5 | Conditional routing by invoice amount |
| 6 | REST API (`/api/`) |
| 7 | Notifications, comments |
| 8 | DRF API refinements |
| 9 | Parallel (all-of) approvals at Executive Review; delegation; escalation; workflow versioning (v1/v2) |
| 10 | Comments and attachments on invoice detail |
| 11 | Developer tooling (validation, simulation, CLI, graphs) |
| 12 | Observability and analytics (REST + admin summary) |
| 13 | Production hardening and the Workflow Dashboard (`/dashboard/`) |

Feature-by-feature coverage is tracked in
[FEATURE_COVERAGE.md](FEATURE_COVERAGE.md).