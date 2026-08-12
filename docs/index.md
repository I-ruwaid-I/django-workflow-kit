# Django Workflow Kit

**A modern, extensible workflow and approval engine for Django applications.**

This documentation covers installation, the quickstart guide and the core
concepts of the package. Feature documentation is written alongside the
corresponding implementation phase.

## Section index

- [Installation](installation.md)
- [Quickstart](quickstart.md)
- [Developer tooling](tooling.md)
- [Testing](contributing.md#testing)
- Concepts
  - [Workflows and states](concepts/workflows.md)
  - [Transitions and actions](concepts/transitions.md)
- Feature guides
  - [States](states.md)
  - [Transitions](transitions.md)
  - [Permissions](permissions.md)
  - [Conditions](conditions.md)
  - [Approvals](approvals.md)
  - [Audit](audit.md)
  - [Comments](comments.md)
  - [Attachments](attachments.md)
  - [Events](events.md)
  - [Notifications](notifications.md)
  - [Workflow versioning](versioning.md)
  - [Django Admin](admin.md)
  - [REST API](api.md)
  - [Analytics](analytics.md)
  - [Observability](observability.md)
  - [Dashboard](dashboard.md)
- Production guides
  - [Production hardening](production.md)
  - [Security](security.md)
  - [Performance](performance.md)
  - [Upgrading](upgrade.md)
- [Troubleshooting](troubleshooting.md)
- [Contributing](contributing.md)
- Phase reports
  - [Phase 9 report](phase9-report.md)
  - [Phase 10 report](phase10-report.md)
  - [Phase 11 report](phase11-report.md)
  - [Phase 12 report](phase12-report.md)
  - [Phase 13 report](phase13-report.md)
  - [Phase 14 pre-release audit](phase14-report.md)

## Status

The project is under active development. Phases 1-13 are complete: the core
workflow engine (states, transitions, executions, atomic transition execution),
permissions, sequential and parallel approvals (all-of / any-of / quorum) with
an append-only audit trail and derived timeline, conditions with conditional
routing, the domain event system with an email/webhook notification layer,
read-only Django admin views, delegation, escalation, SLA tracking, workflow
versioning (immutable numbered definitions with version-bound executions), the
optional DRF REST API for executions, actions, transitions, history, timeline,
approvals, delegation and escalation, collaboration on executions — comments
and file attachments recorded in the timeline and observable through domain
events — and a developer experience layer: declarative workflow parsing, static
validation with structured reports, introspection and path enumeration, dry-run
simulation, action diagnostics (`explain` / `why-not`), DOT/Mermaid graphs, the
`python -m workflow_kit.cli` command line interface and testing utilities.

Phase 12 adds observability and analytics: read-only aggregate metrics and
duration statistics over executions, approvals, SLA and versions (with a
dependency-free Prometheus text exposition), per-state turnaround analysis with
bottleneck detection, SLA compliance and escalation analytics, a structured
event logger with correlation ids, DRF analytics endpoints gated by a dedicated
permission, and an admin analytics summary page.

Phase 13 adds production hardening: deterministic concurrency and idempotency
for workflow versioning under parallel first use, database performance work
(select_related/prefetch_related query optimization, query-count regression
tests, and justified indexes on execution state and started-at ordering), a
security audit covering the authorization boundary, tenant/object isolation,
sensitive-data logging hygiene, attachment security (size and content-type
policy, path-traversal-resistant file names, opt-in public URLs), REST and admin
permissions, plus the **Workflow Dashboard** — a server-rendered Django app
(no frontend framework) with overview metrics, My Work, searchable/filterable/
paginated executions, execution detail (state, version, timeline, audit,
approvals, comments, attachments), and analytics screens, all consuming the
existing engine, analytics and service layers behind the same permissions the
REST API enforces. Phase 14 is the 1.0 release-readiness audit and release
candidate preparation; it does not publish the package. See the
[Phase governance](../AGENTS.md) and
[CHANGELOG.md](../CHANGELOG.md) for details.
