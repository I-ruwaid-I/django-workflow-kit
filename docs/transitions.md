# Transitions

*(Implemented in Phase 1.)*

A transition moves an execution between states. A transition has a `name` (the
action that triggers it), a `source` state and a `target` state:

```python
from workflow_kit import Transition

Transition(
    name="approve",
    source="manager_review",
    target="finance_review",
)
```

Transitions are declared on a `Workflow`, either as `Transition` objects or as
`(name, source, target)` tuples:

```python
workflow = Workflow(
    name="invoice_approval",
    initial="draft",
    states=["draft", "manager_review", "finance_review", "approved", "rejected"],
    transitions=[
        ("submit", "draft", "manager_review"),
        ("approve", "manager_review", "finance_review"),
        ("approve", "finance_review", "approved"),
        ("reject", "manager_review", "rejected"),
    ],
)
```

References to unknown states and duplicate `(source, name)` pairs raise
`WorkflowConfigurationError` at definition time.

## Inspecting transitions

```python
workflow.transitions_from("manager_review")  # list[Transition]
workflow.actions_from("manager_review")      # ["approve", "reject"]
workflow.transition_for("draft", "submit")   # Transition | None
```

## Atomic execution

Executing a transition validates the execution's current state, then persists
the new state atomically in a transaction while the execution row is locked
(`select_for_update` where the backend supports it). Validation and the state
change never run partially.

Transitions enforce:

- Correct source state → `InvalidTransitionError`
- Not running against a completed workflow → `WorkflowAlreadyCompletedError`
- Conditions (Phase 4) failing on every candidate → `ConditionFailedError`
- More than one condition passing for an action → `WorkflowConfigurationError`

Permissions (Phase 2) and conditions (Phase 4) plug into the same lifecycle:

```python
execution.transition("approve", user=user)
# engine-level equivalent:
workflow.transition(execution, "approve", user=user)
```