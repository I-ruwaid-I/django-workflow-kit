# Concepts: workflows and states

A **workflow** defines a process such as *Invoice Approval*. A **state**
represents the current stage of an execution:

```
draft → manager_review → finance_review → approved
                                    ↘ rejected
```

## Workflow

- Has a stable machine-readable `name`.
- Defines an `initial` state.
- Lists all states and transitions.

## State

- Uses stable identifiers (`manager_review`), never display labels.
- May carry a human-readable `label` such as *"Manager Review"*.
- May be terminal (completed states) such as `approved` / `rejected`.

## Workflow execution

A workflow runs against a specific business object (an `Invoice`, a
`PurchaseOrder`, a `LeaveRequest`), tracking its current state.

See [States](../states.md) and [Transitions](../transitions.md) for the
details implemented per phase.