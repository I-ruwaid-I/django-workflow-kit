# Phase 9 — Advanced Workflows & Versioning: Completion Report

**Status:** Implemented, tested, documented, and green across all quality gates.
Package version bumped to `0.2.0`.

## Scope

Phase 9 delivered the final package capabilities: advanced approval modes,
delegation, escalation, SLA tracking, and **workflow versioning**. This report
focuses on the workflow versioning work completed in this session and the
quality gates that now pass.

## Workflow versioning

Releases a workflow safely after it is in production: the definition becomes a
numbered, immutable snapshot (`WorkflowVersion`), and every execution is bound
to the version it started with — it never silently switches to a newer
definition mid-flight.

| Capability | Details |
| ---------- | ------- |
| Model | `WorkflowVersion` (per-workflow sequential numbers; `DRAFT` / `PUBLISHED` / `RETIRED`; JSON definition snapshot; changelog; created/published/retired timestamps) |
| Engine | `workflow_kit.engine.versioning`: `ensure_workflow_version`, `create_workflow_version`, `update_version`, `publish_version`, `retire_version`, `active_version`, `resolve_start_version`, `serialize_workflow`, `deserialize_workflow`, `get_version_workflow` (cached per version by `updated_at`) |
| Execution binding | `WorkflowExecutive.start(...)` pins each execution to the active version (or an explicit `version=`); transitions resolve the pinned definition under the transaction lock |
| Immutability | Published definitions are validated on publish; `update_version` only edits drafts and eagerly validates the replacement |
| Audit/timeline | Every event records the workflow version in its metadata |
| Upgrade path | `ensure_workflow_version` snapshots the registered definition as v1 and pins pre-existing unversioned executions; data migration `0004` does the same for production databases and **refuses to invent history** for non-serializable workflows |
| Concurrency | Strictly increasing version numbers; row-locked publish/retire/decision paths prevent collisions |
| Public API | `Workflow.active_version / create_version / publish_version / retire_version / update_version / versions / version`; `WorkflowVersionError` exported from the package top level |
| Admin | Read-only `WorkflowVersionAdmin`; executions admin surfaces the pinned version |

### What can be versioned

Only declarative, JSON-safe definitions: built-in field conditions + logical
operators, string/`None` permissions, and string approvers. Custom
`Condition` classes, callable/`PermissionProvider` permissions and callable
approvers raise `WorkflowVersionError`; such workflows stay unversioned
(legacy definition-in-Python behavior).

## Demonstration (Invoice Approval demo)

- `invoices/workflow.py` now builds the definition through
  `build_invoice_workflow(executive_threshold=...)`.
- The first invoice publishes **version 1**; every execution is pinned to it.
- `services.publish_invoice_v2` publishes a **version 2** (threshold 25 000).
- New tests prove running executions stay on v1 while new ones bind to v2
  (identical 15 000 invoice takes the v1 Executive route / the v2 direct route).
- `scripts/demo_smoke.py` now exercises v1/v2 over the real demo DB and prints
  the version each execution is pinned to.

## Testing

| Suite | Result |
| ----- | ------ |
| `tests/test_versioning.py` | **40 passed** (lifecycle, immutability, serialization, introspection, admin, upgrade binding, concurrent publish/start) |
| Full package suite | **276 passed** |
| Demo suite (`examples/invoice_approval`) | **54 passed** |
| Coverage (`--source=workflow_kit`, fail-under=90) | **90%** |

Note: the test project now uses a **file-backed SQLite test database**
(`TEST.NAME`) instead of the default in-memory DB, because Django deliberately
ignores `close()` on in-memory databases — worker-thread connections in the
concurrency tests leaked and tripped the suite's `filterwarnings`
`ResourceWarning=error`. A real file makes `close()` effective and gives the
concurrency tests genuine SQLite file-lock semantics (`timeout=60`).

## Quality gates (all green)

| Gate | Command | Result |
| ---- | ------- | ------ |
| Lint | `ruff check .` | Pass (0 errors) |
| Format | `ruff format --check .` | Pass (109 files) |
| Types | `mypy workflow_kit` | Pass (58 source files) |
| Build | `python -m build` | `django_workflow_kit-0.2.0` sdist + wheel |
| Metadata | `twine check dist/*` | PASSED |
| Migrations | `makemigrations --check --dry-run workflow_kit` | No changes detected |
| Demo migrate | `manage.py migrate` (invoice_approval) | `0004 ... OK` |
| Demo smoke | `scripts/demo_smoke.py` | Runs end-to-end incl. v1/v2 |

## Documentation

- New `docs/versioning.md` guide, linked from `docs/index.md`; index status
  updated.
- `README.md` features list includes workflow versioning.
- Demo `README.md` and `FEATURE_COVERAGE.md` document the v1/v2 flow.
- `CHANGELOG.md` Unreleased section updated (versioning + advanced workflows).

## Files added/changed this session

- `workflow_kit/engine/versioning.py` — fixed `deserialize_workflow` to wrap
  `WorkflowConfigurationError` in `WorkflowVersionError`; added
  `_bind_legacy_executions` so `ensure_workflow_version` pins pre-existing
  unversioned executions.
- `workflow_kit/engine/workflow.py`, `workflow_kit/engine/execution.py`,
  `workflow_kit/models/execution.py`, `workflow_kit/migrations/0004_...py`,
  `workflow_kit/models/version.py`, `workflow_kit/admin/__init__.py`,
  `workflow_kit/api/*`, `workflow_kit/__init__.py` — versioning integration.
- `tests/test_versioning.py` — fixed 8 failing tests + 2 concurrency errors.
- `tests/test_project/settings.py` — file-backed test DB + SQLite `timeout=60`.
- `examples/invoice_approval/invoices/{workflow,services}.py`, demo
  `test_workflow.py`, `README.md`, `FEATURE_COVERAGE.md`.
- `scripts/demo_smoke.py` — versioning smoke + idempotent invoice numbering.
- `docs/versioning.md`, `docs/index.md`, `README.md`, `CHANGELOG.md`.
- `pyproject.toml`, `workflow_kit/__init__.py` — version `0.2.0`.

## Recommendation

Phase 9 is complete and all gates pass. Ready for review/commit; Phase 10
(comments, attachments, and further advanced capabilities) can begin after
approval.