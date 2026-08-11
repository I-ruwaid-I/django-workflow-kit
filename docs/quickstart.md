# Quickstart

Define a workflow with a declarative API, attach it to a business model, and
perform transitions with a small, understandable API.

```python
from workflow_kit import State, Transition, Workflow

invoice_workflow = Workflow(
    name="invoice_approval",
    initial="draft",
    states=[
        State("draft", label="Draft"),
        State("manager_review", label="Manager Review"),
        State("finance_review", label="Finance Review"),
        State("approved", label="Approved"),
        State("rejected", label="Rejected"),
    ],
    transitions=[
        ("submit", "draft", "manager_review"),
        ("approve", "manager_review", "finance_review"),
        ("approve", "finance_review", "approved"),
        ("reject", "manager_review", "rejected"),
        ("reject", "finance_review", "rejected"),
    ],
)
```

The definitions are pure Python state machines. Creating a workflow with
`register=True` (the default) makes it available globally as
`get_workflow("invoice_approval")`. Configuration is validated eagerly:
unknown states, duplicate names and invalid transitions raise
`WorkflowConfigurationError` at import time.

## Running executions

A workflow runs against a business object as a
`WorkflowExecution` (an ORM record with a generic foreign key). Start one
explicitly, or retrieve the existing execution for an object:

```python
execution = invoice_workflow.start(invoice)     # first time
execution = invoice_workflow.get_execution(invoice)   # afterwards

execution.current_state      # "draft"
execution.state_label        # "Draft"
execution.available_actions()  # ["submit"]
execution.can_transition("approve")  # False
```

## Executing transitions

```python
execution.transition("submit", user=user)   # user reserved for Phase 2
```

After a transition the execution object reflects the new state:

```python
execution.current_state      # "manager_review"
execution.available_actions()  # ["approve", "reject"]
```

Invalid actions raise `InvalidTransitionError`; calling a transition on a
completed workflow raises `WorkflowAlreadyCompletedError`. Every transition is
wrapped in an atomic transaction and locks the execution row, so two
concurrent actions cannot corrupt the state.

The workflow object also exposes the engine-level API:

```python
invoice_workflow.transition(execution, "approve", user=user)
invoice_workflow.current_state(execution)
invoice_workflow.available_actions(execution, user=user)
invoice_workflow.is_terminal("approved")   # True
```

## Approvals, audit & timeline

Every non-terminal state an execution reaches creates a pending
[approval](approvals.md). Decide it with the approval API:

```python
execution.pending_approvals()          # approvals waiting for a decision
execution.approve(manager)             # approve the current step
execution.reject(finance, reason="Missing quotation")
```

Decisions are authorized by the transition's permission, applied atomically
with the state change, and recorded in the append-only [audit trail](audit.md):

```python
execution.history()          # WorkflowEvent rows, ordered chronologically
execution.timeline()         # derived, structured [timeline](timeline.md) view
```

## Conditions and conditional routing

Transitions may carry [conditions](conditions.md) that restrict when they can
run. Multiple transitions sharing an action name and source branch the
execution to different targets — conditional routing:

```python
from workflow_kit import GreaterThan, LessThanOrEqual, Transition

Transition(
    "approve",
    "finance_review",
    "approved",
    conditions=[LessThanOrEqual("amount", 10_000)],
),
Transition(
    "approve",
    "finance_review",
    "executive_review",
    conditions=[GreaterThan("amount", 10_000)],
),
```

The engine evaluates the conditions on `can_transition()` /
`available_actions()` and re-evaluates them against fresh data at execution
time. An action whose every candidate fails is hidden from introspection and
raises `ConditionFailedError` if executed.

## Try it

Run the Invoice Approval example:

```bash
python examples/invoice_approval/manage.py migrate
python examples/invoice_approval/manage.py runserver
```