# Workflow Versioning

*(Implemented in Phase 9.)*

Workflow versioning lets an installation evolve a workflow definition while
keeping every **already-running execution attached to the definition version
it started with**. An execution never silently switches to a newer definition.

Under the hood each version is an immutable JSON snapshot of the definition:

- the workflow's **states** (name + label),
- its **transitions** (source, target, permission, label, conditions),
- its **approval requirements** per state.

Version numbers are **per-workflow and sequential** (1, 2, 3, …). Only the
snapshot is authoritative: once a version is published its definition is fixed.

## Version lifecycle

Each version lives in one of three states:

| State       | Meaning                                              |
| ----------- | ---------------------------------------------------- |
| `DRAFT`     | Editable. Cannot start new executions.                |
| `PUBLISHED` | Selectable by new executions (see *active version*). |
| `RETIRED`   | No longer selectable by new executions.              |

The **active version** of a workflow is its highest-numbered published
version. A new execution binds to the active version unless one is passed
explicitly.

## Setup

Before the first execution, create and publish version 1:

```python
from workflow_kit import get_workflow
from workflow_kit.engine.versioning import ensure_workflow_version

invoice_workflow = get_workflow("invoice_approval")
ensure_workflow_version(invoice_workflow)
```

`ensure_workflow_version` snapshots the current **registered** definition,
publishes it as version 1 and **pins any pre-existing unversioned executions**
to it — the recommended upgrade path for installations that adopted the
package before versioning existed.

> **Upgrade note:** existing production data is upgraded by migrating the
> package (`python manage.py migrate`). The generated data migration
> reconstructs version 1 for every workflow that has executions and refuses to
> run (raising) if a definition cannot be rebuilt safely — it never invents
> historical data for workflows built from non-serializable elements.

## Starting executions

`WorkflowExecutor.start(...)` binds every new execution to the active version:

```python
execution = invoice_workflow.start(invoice)
execution.workflow_version_number  # e.g. 1
```

You may pin a specific version explicitly (`version=` accepts an int or a
`WorkflowVersion`); published versions are always allowed, and `retired`
versions are rejected unless `allow_unpublished=True` is passed.

## Publishing a revision

Create a draft (optionally cloned from an existing version), revise it, and
publish:

```python
draft = invoice_workflow.create_version(from_version=1)
revised = build_definition_v2()          # your new definition (same name)
invoice_workflow.update_version(draft, revised, changelog="Raise threshold")
invoice_workflow.publish_version(draft, changelog="Raise threshold")
```

- `update_version` only edits drafts and eagerly validates the replacement.
- `publish_version` requires a `DRAFT` version and rejects definitions that
  cannot be serialized.
- `retire_version(...)` retires a published version so new executions stop
  selecting it.

New executions now bind to the published revision; executions already running
keep their original version and behave exactly as before.

## What can be versioned

Only **declarative, JSON-safe** definitions can be snapshotted:

- **Conditions:** the built-in field conditions (`FieldEquals`,
  `FieldNotEquals`, `GreaterThan`, `GreaterThanOrEqual`, `LessThan`,
  `LessThanOrEqual`, `IsTrue`, `IsFalse`) and the logical operators
  `All`, `Any`, `Not`.
- **Permissions:** `None`, Django permission strings, and lists of permission
  strings.
- **Approvers:** group names / usernames / email addresses (strings).

Custom `Condition` classes, callable/`PermissionProvider` permissions and
callable approvers cannot be represented in JSON; a version snapshot that uses
them fails validation with `WorkflowVersionError`. Such workflows stay
unversioned (legacy definition-in-Python behavior) unless the definition is
refactored to use built-ins.

## Reading a versioned execution

The execution's own version is authoritative for its lifecycle:

- `execution.workflow_version_number` — the pinned version number.
- `get_version_workflow(version)` — resolve a stored version back to a live
  `Workflow` you can inspect or execute.
- Audit events and the timeline carry the version in their metadata.

The resolved definition is cached per version (keyed by its `updated_at`), so
draft edits are picked up without explicit cache invalidation.

## Concurrency

Versions are created so that each workflow gets a strictly increasing number;
the engine locks the version row on publish/retire/decision paths so
simultaneous publishes cannot collide or let a retired version start new
executions.

## See also

- [Approvals](approvals.md) — approval requirements snapshot alongside the
  versioned transitions.
- [Audit](audit.md) — every event records the workflow version it belonged to.