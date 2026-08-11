# States

*(Implemented in Phase 1.)*

States represent a stage of a workflow execution. A state has a stable,
machine-readable `name` (never a display label) and an optional human-readable
`label`.

```python
from workflow_kit import State

draft = State("draft")                     # label defaults to "Draft"
manager_review = State("manager_review", label="Manager Review")
```

- **Initial state**: where every execution begins (`Workflow(initial=...)`).
- **Normal states**: intermediate stages such as `manager_review`.
- **Terminal states** — states with no outgoing transitions, such as
  `approved` / `rejected`. Reaching a terminal state marks the execution
  completed; further transitions raise `WorkflowAlreadyCompletedError`.

An empty state name raises `WorkflowConfigurationError`.

## Using states on a workflow

```python
workflow.states              # tuple of State, in definition order
workflow.state("approved")   # State; raises WorkflowNotFoundError if missing
workflow.initial             # "draft"
workflow.is_terminal("approved")   # True
workflow.terminal_states     # frozenset, e.g. {"approved", "rejected"}
```

`State` is compared by name, so `State("draft") == "draft"`. Labels are only
for display and never used as identifiers.