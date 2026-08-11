# Feature Coverage Matrix

Tracks which `django-workflow-kit` capabilities are genuinely demonstrated by
the Invoice Approval Demo, verified by tests, and documented.

This matrix is updated whenever a package feature is completed. A feature is
"Done" only when it works through the public API, has a demo, has tests, and
is documented and PASSED.

Legend:

- **Demo**: used naturally in the demo application
- **Test**: covered by an automated test
- **Docs**: documented in the demo README / main documentation

| Feature          | Demo | Test | Docs | Notes |
| ---------------- | ---- | ---- | ---- | ----- |
| States           | Yes  | Yes  | Yes  | `State` in `invoices/workflow.py` |
| Transitions      | Yes  | Yes  | Yes  | submit / approve / reject |
| Executions       | Yes  | Yes  | Yes  | `invoice.execution` / current state |
| Permissions      | Yes  | Yes  | Yes  | Groups + Django permissions per transition; denied users rejected at engine level; see README permission matrix |
| Approvals        | Yes  | Yes  | Yes  | Decisions through `execution.approve` / `reject` with persisted reasons |
| Audit            | Yes  | Yes  | Yes  | `execution.history()` / audit trail |
| Timeline         | Yes  | Yes  | Yes  | `execution.timeline()` derived from audit |
| Comments         | Yes  | Yes  | Yes  | Phase 10: comment widget on the invoice detail page; `comment_added` audits/events; see `test_comments.py` and `test_views.py` |
| Conditions       | Yes  | Yes  | Yes  | Phase 4: conditional routing by amount (≤ 10 000 finalized, > 10 000 to Executive Review); conditions re-evaluated on fresh state |
| Notifications    | Yes    | Yes    | Yes  | Email notification on completion wired via the event dispatcher at demo startup; demo event handler subscribed in `apps.py`; see `test_events.py` and README (notifications demonstrated on completion) |
| Delegation       | Yes    | Yes    | Yes  | `execution.delegate` through `services.delegate_invoice`; see `test_advanced.py` |
| Escalation       | Yes    | Yes    | Yes  | `execution.escalate` through `services.escalate_invoice`; see `test_advanced.py` |
| SLA              | Pending | Pending | Pending | Future |
| Parallel Approval| Yes    | Yes    | Yes  | Executive Review uses `ApprovalMode.ALL` (Executive + Finance) |
| Versioning       | Yes    | Yes    | Yes  | `build_invoice_workflow` factory + `services.publish_invoice_v2`; executions pinned to immutable numbered versions (v1/v2 demo test) |
| REST API         | Yes    | Yes    | Pending | Phase 6: `workflow_kit.api` DRF viewset mounted at `/api/`; execution, actions, transition, history, timeline and approvals endpoints. |
| Admin            | Yes    | Yes    | Yes  | Executions, approvals, comments, attachments and audit trail read-only; never bypasses workflow authorization. |
| Attachments      | Yes    | Yes    | Yes  | Phase 10: file upload widget on the invoice detail page; stored via Django's default storage; `attachment_added` audits/events |
| Analytics        | Yes    | Yes    | Yes  | Phase 12: read-only aggregates over executions/approvals/SLA/versions (counts, completion times, state durations, bottlenecks, SLA compliance, escalations); admin analytics summary + REST endpoints; see `docs/analytics.md` |
| Observability    | Yes    | Yes    | Yes  | Phase 12: `correlation_id` + `StructuredEventLogger` on the existing event dispatcher (auto-installed by `AppConfig.ready()`); see `docs/observability.md` |
| Production concurrency | Yes | Yes | Yes | Phase 13: deterministic versioning under parallel first use; `tests/test_phase13_concurrency.py` |
| Security         | Yes    | Yes    | Yes  | Phase 13: authorization boundary, tenant/object isolation, logging hygiene, attachment size/content-type/path-traversal policy, admin read-only; `tests/test_phase13_security.py`; see `docs/security.md` |
| Performance      | Yes    | Yes    | Yes  | Phase 13: `select_related` list, query-count regression tests, `current_state` / `-started_at` indexes; see `docs/performance.md` |
| Dashboard        | Yes    | Yes    | Yes  | Phase 13: server-rendered `workflow_kit.dashboard` mounted at `/dashboard/` (Overview, My Work, Executions, Execution detail, Analytics); `invoices/tests/test_dashboard.py`; see `docs/dashboard.md` |

## Phase 1 baseline

| Deliverable        | Demo | Test | Docs |
| ------------------ | ---- | ---- | ---- |
| Standalone Django project | Yes | Yes | Yes |
| Invoice model      | Yes | Yes | Yes |
| Workflow definition via public API | Yes | Yes | Yes |
| Executions / current state | Yes | Yes | Yes |
| Transitions (submit/approve/reject) | Yes | Yes | Yes |
| Invalid / completed transitions handled | Yes | Yes | Yes |
| Basic views / templates | Yes | Yes | Yes |
| Consumes package public API | Yes | Yes | Yes |