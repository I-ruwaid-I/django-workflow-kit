# Django Workflow Kit

**A modern, extensible workflow and approval engine for Django applications.**

Django developers can add a sophisticated workflow system to an existing
Django project without building the engine themselves. Add state machines,
approval workflows, audit trails and timelines with a small, understandable
Python API.

> **Simple to start. Powerful when needed. Django-native.**

---

## The problem

Most business applications eventually need to model processes:

- Create an invoice, submit it for approval, get manager and finance sign-off.
- Track a leave request from draft through approval.
- Route a document through review, verification and publication.

Hand-rolled workflow code quickly becomes a tangle of scattered `if`/`else`
checks, duplicated state guards, and unverifiable audit stories. Django
Workflow Kit moves that complexity inside a well-tested engine while keeping a
clean public API.

## Features

- Declarative workflow, state and transition definitions
- State machines with stable identifiers and human-readable labels
- Atomic, concurrency-safe transitions
- Django-native permission checks (users, groups, model permissions)
- Sequential, parallel, any-of and all-of approvals
- Workflow versioning: immutable numbered definitions with version-bound
  executions that never silently change definition mid-flight
- Append-only audit trail and derived timelines
- Comments and file attachments on executions (recorded in the timeline and
  observable as domain events; files stored via Django's storage abstraction)
- Extensible conditions evaluated against a typed context — never `eval`
- Pluggable notification providers; email and signed webhooks are included,
  with Slack, Teams or other channels added as custom providers
- Developer experience: declarative workflow definitions, static validation
  with structured reports, introspection, dry-run simulation, action
  diagnostics (`explain` / `why-not`), DOT/Mermaid graphs, a
  `python -m workflow_kit.cli` command line interface, and testing helpers
- Observability and analytics: read-only aggregate metrics and duration
  statistics over executions, approvals, SLA and versions, per-state
  turnaround analysis with bottleneck detection, SLA compliance and escalation
  analytics, a dependency-free Prometheus text exposition, structured event
  logging with correlation ids, DRF analytics endpoints (permission-gated) and
  an admin analytics summary page
- Workflow Dashboard: a server-rendered Django app (no frontend framework)
  with an overview, My Work queue, searchable/filterable/paginated executions,
  execution detail (state, version, timeline, audit, approvals, comments,
  attachments) and analytics screens — all behind the same permissions as the
  REST API
- Production hardening: deterministic concurrency and idempotency for version
  creation, query-count regression tests, justified indexes, a security audit
  of the authorization boundary and attachment policies
- Optional Django REST Framework integration
- Minimal dependencies: Python and Django only at its core

## Roadmap

The project is developed in phases. See [CHANGELOG.md](CHANGELOG.md) and
[Phase Overview](docs/index.md#status).

## Architecture

```text
Django Application
       │
       ▼
Workflow Definition
       │
       ▼
Workflow Engine
       ├── States · Transitions · Conditions · Permissions
       ├── Approvals · Audit · Timeline · Notifications
       ▼
Django ORM
```

The engine is independent of any specific business model and works with
arbitrary Django models.

## Quickstart

```bash
pip install django-workflow-kit
```

Add to `INSTALLED_APPS`, then define a workflow:

```python
from workflow_kit import Workflow

invoice_workflow = Workflow(
    name="invoice_approval",
    initial="draft",
    states=["draft", "manager_review", "finance_review", "approved", "rejected"],
    transitions=[
        ("submit", "draft", "manager_review"),
        ("approve", "manager_review", "finance_review"),
        ("approve", "finance_review", "approved"),
        ("reject", "*", "rejected"),
    ],
)
```

Start an execution and perform transitions:

```python
execution = invoice_workflow.start(invoice, user=user)
execution.transition("submit", user=user)
execution.approve(user)
execution.reject(user, reason="Missing quotation")
```

## Documentation

Full documentation lives in [docs/](docs/):

- [Installation](docs/installation.md)
- [Quickstart](docs/quickstart.md)
- [Concepts](docs/index.md)
- [Developer CLI](docs/tooling.md)

## Testing

```bash
pip install -e ".[dev]"
pytest
```

## Contribution

Guidelines in [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md) for how to report vulnerabilities.

## License

Distributed under the [MIT License](LICENSE).
