# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- Phase 13 - production hardening (no version bump):
  - Deterministic concurrency and idempotency: `engine.versioning`
    `ensure_workflow_version` now retries on concurrent version creation with
    `transaction.atomic()` + `IntegrityError` fallback, so parallel first use
    collapses to a single v1 (`tests/test_phase13_concurrency.py`, 16 tests).
  - Database performance: `api.views.get_queryset` now uses
    `select_related("content_type", "workflow_version")`, removing an N+1 for
    versioned execution lists; new query-count regression tests
    (`tests/test_phase13_queries.py`, 5 tests) cap queries for list, detail +
    actions, history/timeline and analytics metrics.
  - Row-level access: justified indexes on `WorkflowExecution` for
    `current_state` and `-started_at` ordering (migration 0006).
  - Security audit (§17–§23 of PHASE13): `AttachmentError` exception added and
    exported; attachment uploads enforce an optional size cap
    (`ATTACHMENT_MAX_SIZE`) and content-type allow-list
    (`ATTACHMENT_ALLOWED_CONTENT_TYPES`); stored file names are sanitized
    against absolute/path-traversal uploads; attachment `url` in the REST API
    is only exposed when `ATTACHMENT_PUBLIC_URLS` is `True`;
    `tests/test_phase13_security.py` (15 tests) covering the authorization
    boundary across GET/POST/PUT/PATCH/DELETE, tenant/object isolation,
    sensitive-data logging hygiene, webhook payloads, admin read-only across
    all registered models, and published-version immutability.
  - Workflow Dashboard (`workflow_kit.dashboard`): a server-rendered Django
    app (templates + static CSS, no frontend framework) with an Overview
    (metrics + per-workflow health), My Work (assignable pending approvals +
    active delegations), searchable/filterable/paginated executions, execution
    detail (state, version, approvals, timeline, comments, attachments, audit)
    and analytics screens. It consumes the existing engine, analytics and
    service layers — never a second source of truth — and applies the same
    permission rule as the REST analytics API (staff or
    `workflow_kit.view_analytics`). Responsive, keyboard-accessible with a
    consistent design system. Mounted in the Invoice Approval demo and the
    package test project; `tests/test_dashboard.py` (15 tests) plus 6 demo
    dashboard tests.

- Phase 12 - observability and analytics (package version bumped to 0.4.0):
  - `analytics.base`: `AnalyticsError`, aware-date parsing (`parse_datetime`),
    the shared `execution_queryset` scope helper and `DurationStats` summary
    statistics (count/average/median/min/max/P95/P99).
  - `analytics.metrics`: `execution_metrics` aggregate counts — started,
    active, completed, rejected, cancelled, failed, escalated,
    SLA-breached — computed with database aggregations and `Exists`
    subqueries (constant query cost regardless of execution volume), plus
    `VersionAnalytics` / `version_analytics` per-version breakdowns.
  - `analytics.duration`: `completion_metrics` (completion times),
    `state_durations` (per-state turnaround reconstructed from the audit
    trail) and `bottlenecks` (states flagged when their average far exceeds
    the rest).
  - `analytics.approvals`: `approval_metrics` and `approval_totals` with
    decision-time statistics and grouping by workflow/version/step/approver/
    status.
  - `analytics.sla`: `sla_metrics` (compliance rate, breaches,
    pending-overdue, average overdue, average completion) and
    `escalation_analytics` (distribution by workflow/state/reason plus average
    escalation delay).
  - `analytics.prometheus`: dependency-free `prometheus_metrics_text`
    exposition and `collect_metrics` dict form - no `prometheus_client`
    dependency.
  - `observability`: `correlation_id` contextvars API and
    `StructuredEventLogger` that subscribes to the existing event dispatcher
    (installed automatically by `AppConfig.ready()` unless
    `WORKFLOW_KIT["STRUCTURED_LOGGING"]` is `False`).
  - REST analytics endpoints under `/api/analytics/` (metrics, completion,
    state durations, bottlenecks, approvals, approval totals, SLA,
    escalations, versions) gated by `IsAnalyticsViewer` (staff or the
    `workflow_kit.view_analytics` permission); `AnalyticsError` maps to
    HTTP 400 with code `invalid_analytics_arguments`.
  - Read-only admin analytics summary page at `/admin/workflow_kit/
    workflowexecution/summary/`.
  - Docs: `docs/analytics.md`, `docs/observability.md`,
    `docs/phase12-report.md`; README, `docs/index.md`, `docs/api.md` and
    `docs/admin.md` updated.

- Phase 11 - developer experience (package version bumped to 0.3.0):
  - `engine.validation`: `ValidationIssue` / `ValidationReport` with
    severities, stable codes and locations; `validate_definition` /
    `validate_many` static analysis (unreachable states, ambiguous routing,
    self-loops, conditional routing, approvals on terminal states);
    `ValidationReport.raise_if_invalid()` raising `WorkflowValidationError`
    with a JSON-safe `payload["issues"]`.
  - `engine.parse`: `parse_workflow_def` builds a `Workflow` from a dict, JSON
    string, file path or file-like object — one shared validation path with
    version snapshots, no `eval`/`exec`.
  - `engine.introspection`: `workflow_to_dict` (JSON-safe dump with
    reachability/terminal metrics), `reachable_states`, `simple_paths`,
    `path_states`, `condition_variants`.
  - `engine.simulation`: `simulate`, `simulate_all`, `verify_always_completes`
    — pure-Python dry-runs with no database writes; `SimStep`/`SimulationResult`,
    optional condition `gate` and `max_steps`; `NoPathFoundError` for
    definitions that cannot always complete.
  - `engine.explain`: `explain` / `why_not` return `ActionExplanation` with
    per-factor `BlockReason` entries (`terminal`, `no_action`, `permission`,
    `condition`, `ambiguous`, `no_satisfying_transition`).
  - `graph`: `to_dot` (Graphviz) and `to_mermaid` (Mermaid) rendering plus
    `render(fmt)` dispatch.
  - `cli`: `python -m workflow_kit.cli` with `deploy`, `validate`,
    `view-workflow`, `simulate`, `explain`, `why-not` and `graph` subcommands;
    refuses to deploy invalid definitions; structured exit codes.
  - `testing`: `WorkflowValidationMixin`, `ExecutionAssertions`, `assert_valid`,
    `workflow_factory`, `SimpleWorkflow`, `workflow_module`, `unregister_all`.
  - Structured exceptions: every `WorkflowError` carries optional `workflow`,
    `state`, `action` and a JSON-safe `payload`; added `WorkflowValidationError`,
    `SimulationError`, `NoPathFoundError`.
  - Docs: new `docs/tooling.md` and `docs/phase11-report.md`; `docs/index.md`,
    `README.md`, `CHANGELOG.md` updated; demo smoke now covers the CLI-facing
    tools (21 checks); 94 new tests (package suite **393 passed**).

- Phase 10 - comments and attachments:
  - `WorkflowComment` model: free-form discussion scoped to one execution,
    with the author (`user`), `text`, `metadata` and `created_at`. The
    `WorkflowComment.author_label` property exposes a stable author name that
    falls back to `anonymous`.
  - `WorkflowAttachment` model: file attachments stored through Django's
    storage abstraction (`FileField` + default storage) with the original
    `name`, `content_type`, `size` and `extension` captured at upload time.
    No third-party storage backend is required.
  - Service layer (`workflow_kit.comments` and `workflow_kit.attachments`):
    `add_comment` / `execution_comments`, `add_attachment` /
    `execution_attachments`. Adding a comment or uploading a file appends a
    `comment_added` / `attachment_added` audit event and emits a
    `workflow.comment_added` / `workflow.attachment_added` domain event, so
    discussion appears in the timeline and event stream like any state change.
  - Execution convenience methods: `execution.add_comment(user, text)` and
    `execution.add_attachment(upload, name=..., user=...)`.
  - Timeline labels `Comment added` / `Attachment added` derived from the
    new audit event codes (`WorkflowEventType.COMMENT_ADDED`,
    `WorkflowEventType.ATTACHMENT_ADDED`).
  - Read-only `WorkflowCommentAdmin` and `WorkflowAttachmentAdmin`.
  - DRF API: `GET/POST /executions/{id}/comments/` and
    `GET/POST /executions/{id}/attachments/` (multipart uploads) on the
    execution viewset, with `CommentSerializer`, `CommentCreateSerializer`,
    `AttachmentSerializer` and `AttachmentCreateSerializer`.
  - Migration `0005` adds both models plus indexes.
  - Invoice Approval demo: comment and attachment widgets on the invoice
    detail page (`/invoices/{id}/comment/` and `.../attach/`), media served in
    DEBUG, and view tests for adding/listing comments and uploading files.
  - New `tests/test_comments.py` and `tests/test_attachments.py` (22 tests:
    convenience methods, audit + domain events, timeline integration, REST
    endpoints, authentication and input validation).
  - Docs: `docs/comments.md` and `docs/attachments.md` guides linked from the
    docs index; README features and timeline/API docs updated.
- Phase 9 - workflow versioning:
  - `WorkflowVersion` model with per-workflow sequential numbering, a
    `DRAFT` / `PUBLISHED` / `RETIRED` lifecycle, a JSON definition snapshot,
    changelog and created/published/retired timestamps. Only declarative,
    JSON-safe definitions are snapshottable (built-in conditions, string
    permissions, string approvers) — everything else raises
    `WorkflowVersionError`.
  - `workflow_kit.engine.versioning`: `ensure_workflow_version`,
    `create_workflow_version`, `update_version`, `publish_version`,
    `retire_version`, `active_version`, `resolve_start_version`,
    `serialize_workflow`, `deserialize_workflow` and
    `get_version_workflow` (cached per version by `updated_at`).
  - **Version-bound executions**: `WorkflowExecutive.start(...)` pins each
    execution to the workflow's active version (or an explicit `version=`),
    and the engine resolves the pinned definition for every transition —
    an execution never silently switches to a newer definition. Audit events
    and the timeline carry the workflow version in their metadata.
  - **Safe upgrade path**: `ensure_workflow_version` snapshots the registered
    definition as version 1 and pins pre-existing unversioned executions to
    it; the shipped data migration (`0004`) does the same for production
    databases and refuses to invent history for non-serializable workflows.
  - Concurrency-hardened version lifecycle: strictly increasing numbers and
    row-locked publish/retire so simultaneous publishes cannot collide.
  - Convenience methods on `Workflow`: `active_version`, `create_version`,
    `publish_version`, `retire_version`, `update_version`, `versions`,
    `version`.
  - Read-only `WorkflowVersionAdmin`; `WorkflowExecutionAdmin` shows the
    pinned version. `WorkflowVersionError` added to the public exception
    surface.
  - Invoice Approval demo end-to-end: definitions built through a
    `build_invoice_workflow(executive_threshold=...)` factory; the first
    invoice publishes version 1, `services.publish_invoice_v2` publishes a
    higher-threshold revision, and tests prove running executions stay on v1
    while new ones bind to v2.
  - New `tests/test_versioning.py` (40 tests: lifecycle, immutability,
    serialization, introspection, admin, upgrade binding, concurrent
    publish/start). Package version bumped to `0.2.0`.
  - Docs: `docs/versioning.md` guide linked from the docs index.
- Phase 9 - advanced workflows:
  - Step approval requirements (`ApprovalRequirement`, `ApprovalMode`) with
    **all-of**, **any-of** and **quorum** voting modes. A step may declare one
    pending `Approval` per approver slot; approvers are resolved at step entry
    from group names, usernames, user instances, `ApproverResolver`
    subclasses or callables (`workflow_kit.approvals.requirements`).
    `Workflow(...)` accepts an `approval_requirements` mapping keyed by state
    name.
  - **Delegation**: an approver can forward a step's slot to another user via
    `execution.delegate(...)`. Decisions made through a delegation are
    authorized against the granter's rights. Delegations are scoped to an
    execution/step, optional expiry, revocable (`delegation.revoke()`),
    recorded in the new `WorkflowDelegation` model and traced as
    `approval_delegated` / `delegation_revoked` events.
  - **Escalation**: `execution.escalate(approver, user=..., reason=...)`
    cancels a step's pending approvals and replaces them with a single any-of
    approval the escalation approver alone decides (`approval_escalated`).
  - **SLA tracking**: each requirement can set an `sla`; deadlines are stored
    on `Approval.due_at` and surfaced through the `overdue_approvals()`
    query helper and the `Approval.is_overdue` property.
  - Self-approval control (`allow_self`) compared against the initiating user
    (`WorkflowExecution.initiated_by`, set via `Workflow.start(..., user=...)`).
  - Concurrency hardening: approval decisions re-read the execution and the
    target approval with `select_for_update` inside one transaction so
    simultaneous votes cannot double-advance a step; sibling approvals are
    cancelled transactionally on advance.
  - DRF API: `delegate` / `escalate` endpoints on `ExecutionViewSet` and
    extended `ApprovalSerializer`; approvals carry `mode`, `order`,
    `assignment` and `is_overdue`.
  - Admin: read-only `Approval` / `WorkflowDelegation` admins; execution admin
    shows the initiating user.
  - Invoice Approval demo: `executive_review` is now a parallel all-of step
    (Executive + Finance), an `Executive` demo account was added, and the demo
    exercises delegation and escalation end-to-end.
- Phase 6 - optional DRF REST API:
  - `workflow_kit.api` package that loads only when Django REST Framework is
    installed; the core remains DRF-free (installed via the `drf` extra).
  - `WorkflowExecutionViewSet` exposing list (filterable by `workflow` /
    `current_state` / `completed`, paginated) and detail (including the
    caller's `available_actions`), plus `actions`, `transition`, `history`,
    `timeline` and `approvals` sub-actions.
  - Business objects are rendered only as `{type, id}` — arbitrary model
    fields and stack traces are never exposed over HTTP; every endpoint
    requires an authenticated user.
  - Engine exceptions mapped to structured JSON errors (`invalid_transition`,
    `permission_denied`, `condition_failed`, `workflow_completed`,
    `approval_not_pending`) via
    `workflow_kit.api.exceptions.workflow_error_handler`; `approve`/`reject`
    route through the approval decision service, other actions through the
    generic transition API.
  - Optional `WorkflowKitPagination` (page size 20, `page_size` query param).
  - Invoice Approval demo mounts the API at `/api/` with an end-to-end REST
    test suite; docs: REST API guide.
- Phase 5 - domain events and notifications:
  - `EventType` vocabulary (`workflow.started/transitioned/completed/
    cancelled/rejected`, `approval.created/approved/rejected`) and an immutable
    `DomainEvent` payload (type, workflow, execution id, `ObjectRef`, actor,
    timestamp, source/target states, action, metadata and unique id).
  - Explicit in-process `EventDispatcher` with `subscribe`/`dispatch`/`clear`,
    `"*"` wildcard subscriptions and fault-isolated handlers; a module-level
    `default_dispatcher` with `subscribe`/`dispatch` aliases.
  - Transaction-aware `capture`/`emit`/`flush`: events buffered in `capture`
    are dispatched in order on success and discarded on failure, so a
    rolled-back transition never delivers events; events emitted outside
    `capture` dispatch immediately.
  - Engine integration: `start` emits `workflow.started`, non-terminal
    transitions emit `workflow.transitioned` + `approval.created`, and
    terminal transitions emit `workflow.completed` /
    `workflow.cancelled` / `workflow.rejected`; approval decisions emit
    `approval.approved` / `approval.rejected`.
  - `NotificationProvider` abstraction, `NotificationRouter`
    (`register`/`install`/`uninstall`/`clear`), `EmailProvider` built on
    Django's mail system, and `WebhookProvider` posting signed
    HMAC-SHA256 JSON payloads (`X-Domain-Signature`, `-Event`,
    `-Event-Id`, `-Timestamp` headers). Webhooks disabled by default.
  - New `WORKFLOW_KIT` settings: `NOTIFICATIONS_ENABLED`,
    `EMAIL_NOTIFICATIONS_ENABLED`, `EMAIL_FROM`, `EMAIL_SUBJECT_PREFIX`,
    `WEBHOOK_NOTIFICATIONS_ENABLED`, `WEBHOOK_URL`, `WEBHOOK_SECRET`.
  - Invoice Approval demo subscribes an `[EVENT]` console logger and an
    email notification on completion via Django's console email backend.
  - Tests for events, transaction semantics, dispatch isolation and the
    notification providers; docs: events and notifications guides.
- Phase 4 - conditions, conditional routing and Django admin:
  - `Condition` interface and a frozen `ConditionContext`
    (`user` / `workflow` / `execution` / `object`) evaluated by every built-in;
    conditions never `eval` user code.
  - Built-in conditions: `FieldEquals`, `FieldNotEquals`, `GreaterThan`,
    `GreaterThanOrEqual`, `LessThan`, `LessThanOrEqual`, `IsTrue` and
    `IsFalse`, supporting dotted paths (`customer.is_verified`); a missing
    attribute raises `ConditionEvaluationError`.
  - Logical operators `All`, `Any` and `Not` in
    `workflow_kit.conditions`.
  - `Transition(..., conditions=...)` accepts a condition or a list; the
    engine evaluates them on `can_transition()` / `available_actions()` and
    re-evaluates against a freshly-persisted business object at execution
    time.
  - Conditional routing: multiple transitions may share an action name and
    branch to different targets. Resolution requires exactly one passing
    candidate; none raises `ConditionFailedError` and is hidden from
    introspection, more than one raises `WorkflowConfigurationError`.
  - Invoice Approval demo routes invoices above `10 000` through an
    `Executive Review` step; new engine-level and demo tests.
  - Read-only Django admin for `WorkflowExecution`, `Approval` and
    `WorkflowEvent` (no add / change / delete, so the admin can never bypass
    workflow authorization).
  - Docs: conditions and admin guides implemented; quickstart/transitions
    updated.
- Phase 3 - approval engine, audit trail and timeline:
  - `Approval` model: one pending approval per non-terminal step, decided
    (`APPROVED` / `REJECTED`) through `execution.approve()` /
    `execution.reject()` with persisted approver, action and reason.
  - Approval decisions run atomically with the state transition, re-read and
    lock the execution row (`select_for_update`), and delegate authorization
    to the Phase 2 permission system.
  - Sequential approvals handled naturally: the next pending approval is
    created as the execution moves into each review state.
  - Append-only `WorkflowEvent` audit model recording start, transitions,
    approval requirements/decisions and completion; `WorkflowEvent.save()`
    rejects updates to existing rows (`AuditError`).
  - `execution.history()` (ordered audit trail) and `execution.timeline()`
    (structured `TimelineEvent` dataclasses exported from the package top
    level); the timeline derives from the audit trail only.
  - Invoice Approval demo now drives approve/reject through the approval API,
    passes rejection reasons and renders the timeline and pending approvals.
  - New tests for approvals, audit, timeline and demo integration; package
    coverage remains 96%.
  - Docs: approvals, audit and timeline pages implemented.
- Phase 1 core workflow engine:
  - `Workflow`, `State` and `Transition` definitions with eager validation
    (unknown states, duplicate names, invalid transitions raise
    `WorkflowConfigurationError`).
  - Global workflow registry (`get_workflow`, `all_workflows`,
    `registry.unregister`).
  - `WorkflowExecution` ORM model (generic foreign key to any business
    object) with `current_state`, `is_completed`, `state_label`, and
    `available_actions` / `can_transition` / `transition` conveniences.
  - Atomic, row-locked transition execution
    (`execute_transition`), with `InvalidTransitionError` and
    `WorkflowAlreadyCompletedError`.
  - Read-only `WorkflowExecution` Django admin registration.
  - Invoice Approval demo now runs its full lifecycle through the public
    API (submit / approve / reject), replacing the old `status` field.
  - Unit, integration and demo tests; coverage 96% on the package.
- Project bootstrap: packaging, CI, test infrastructure and documentation
  skeleton.

## 1.0.0 - 2026-08-12

First stable 1.0 release.

### Added

- 1.0 release-readiness preparation:
  - Added migration `0007` to provision the documented
    `workflow_kit.view_analytics` permission on `WorkflowExecution`.
  - Added PyPI project URLs, the Django 6.2 classifier, package data for admin
    templates and a minimal `mkdocs.yml` for the documented `docs` extra.
  - Removed placeholder Celery and Redis extras from package metadata because
    no integrations are shipped yet.
  - Corrected README and documentation drift for quickstart API usage,
    compatibility, analytics permissions, repository URLs and security support
    policy.
  - Public API frozen and verified (`workflow_kit.__all__`), coverage ≥ 90%,
    full packaging and clean-room verification passed.

## 0.1.0 - 2026-08-08

### Added

- Initial repository structure
- `pyproject.toml` packaging for `django-workflow-kit`
- Django application skeleton (`workflow_kit`)
- Exception hierarchy (`WorkflowError` and subclasses)
- Configuration proxy (`WORKFLOW_KIT` Django settings)
- Test project with an `Invoice` demo model
- Pytest + pytest-django test suite
- GitHub Actions CI (lint, typecheck, matrix tests, build)
- Documentation skeleton, README, LICENSE, CONTRIBUTING and SECURITY
