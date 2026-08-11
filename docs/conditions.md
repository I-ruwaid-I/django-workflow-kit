# Conditions

*(Implemented in Phase 4.)*

Conditions restrict when a transition may run, evaluated against a controlled
context. They are the engine's mechanism for **conditional routing**: several
transitions can share one action name and branch to different target states
based on the business object's current values.

```python
from workflow_kit import Transition, Workflow
from workflow_kit.conditions import GreaterThan, LessThanOrEqual

workflow = Workflow(
    name="invoice_approval",
    initial="draft",
    states=["draft", "manager_review", "finance_review", "approved", "rejected"],
    transitions=[
        ("submit", "draft", "manager_review"),
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
        ("reject", "manager_review", "rejected"),
    ],
)
```

When `approve` is executed from `finance_review`, the engine evaluates every
candidate transition's conditions against the current business object and
requires **exactly one winner**:

- one passing branch → that target is executed;
- no passing branch → the action cannot run: introspection hides it and
  execution raises `ConditionFailedError`;
- more than one passing branch → the routing is ambiguous and raises
  `WorkflowConfigurationError`. Overlapping conditions on one action are a
  configuration error, so branches must be mutually exclusive.

## The condition interface

Any `Condition` subclass implements `evaluate(context) -> bool`. The context is
a frozen `ConditionContext` that exposes exactly four fields:

| Field      | Meaning                                            |
| ---------- | -------------------------------------------------- |
| `user`     | The acting user, or `None`                         |
| `workflow` | The `Workflow` definition                          |
| `execution`| The `WorkflowExecution` being evaluated            |
| `object`   | The business object (see below)                    |

Conditions never receive raw request objects or unrestricted globals, and the
engine never evaluates user-supplied code — no `eval(...)` anywhere.

## Built-in conditions

| Condition              | Passes when                         |
| ---------------------- | ----------------------------------- |
| `FieldEquals(f, v)`   | `object.f == v`                     |
| `FieldNotEquals(f, v)` | `object.f != v`                     |
| `GreaterThan(f, v)`    | `object.f > v`                      |
| `GreaterThanOrEqual(f)`| `object.f >= v`                     |
| `LessThan(f, v)`       | `object.f < v`                      |
| `LessThanOrEqual(f, v)`| `object.f <= v`                     |
| `IsTrue(f)`           | `object.f is True`                  |
| `IsFalse(f)`          | `object.f is False`                 |

Fields may be dotted paths, e.g. `IsTrue("customer.is_verified")`. A missing
attribute raises `ConditionEvaluationError` so configuration mistakes are
explicit rather than silently passing.

## Composability

`workflow_kit.conditions` also exposes logical operators:

```python
from workflow_kit.conditions import All, Any, Not

All(GreaterThan("amount", 10_000), IsTrue("customer.is_verified"))
Any(IsTrue("priority_override"), GreaterThan("amount", 100_000))
Not(LessThan("amount", 10))  # exactly one child, inverted
```

`Transition.conditions` accepts a single condition or a list; every condition
must pass (logical AND) for the transition to be available.

## Evaluation semantics

Conditions are evaluated in two places so they can never get out of sync:

1. **Introspection** — `can_transition()` and `available_actions()` skip
   transitions whose conditions fail.
2. **Execution** — `transition()` and the approval path
   (`execution.approve()` / `execution.reject()`) resolve the target under the
   transaction lock, re-reading the business object fresh from the database so
   decisions always reflect current state.

## Custom conditions

```python
import random
from workflow_kit import Condition

class CoinFlip(Condition):
    def evaluate(self, context) -> bool:
        return random.random() < 0.5
```

Write deterministic conditions in production; the engine evaluates them
whenever workflow state is inspected.