# Developer Tooling

Phase 11 ships a set of developer-facing tools for inspecting, validating,
exercising and visualizing workflow definitions. Everything here is **pure
Python** — it never calls `django.setup()` and never touches the database.

## Command line interface

`python -m workflow_kit.cli` provides the following subcommands. Most accept a
**registered workflow name** (from `registry`) or a **path to a JSON workflow
definition**:

```text
deploy         Register workflow definitions from a JSON file or Python module
validate       Statically analyse registered or declared workflows
view-workflow  Dump a full description of a workflow as JSON
simulate       Dry-run a sequence of actions (or enumerate every path)
explain        Explain whether an action can run from a state
why-not        Report why an action cannot execute from a state
graph          Render a workflow as DOT or Mermaid
```

### Validate

```bash
python -m workflow_kit.cli validate path/to/workflow.json
python -m workflow_kit.cli validate --name invoice_approval
```

Static analysis covers:

- **reachability** — states that can never be reached from the initial state
  (warning);
- **ambiguous routing** — an action with several transitions but no conditions
  to disambiguate them (error; such an action can never resolve safely);
- **self-loops** — an unconditional loop that repeats forever (warning);
- **conditional routing** — actions routed to multiple targets by conditions
  (info).

The exit code is non-zero when any workflow fails validation.

### Simulate (dry-run)

```bash
python -m workflow_kit.cli simulate invoice_approval --actions submit,approve
python -m workflow_kit.cli simulate invoice_approval --all
```

`--actions` replays an action sequence against the definition. `--all`
enumerates every simple (cycle-free) path from the initial state to a terminal
state. Simulation never creates executions or audit records.

### Explain / why-not

```bash
python -m workflow_kit.cli explain   invoice_approval approve --state review
python -m workflow_kit.cli why-not   invoice_approval approve --state review
```

`explain` reports whether an action is applicable and, when it is not, each
blocking factor with a stable `kind` identifier:

- `terminal` — the workflow is in a terminal state;
- `no_action` — the action does not exist from the current state;
- `permission` — the user does not satisfy a transition's permission;
- `condition` — a transition's conditions fail (the blocked conditions are
  listed by class name);
- `ambiguous` — conditional routing resolves to multiple passing transitions;
- `no_satisfying_transition` — no candidate is both authorized and
  condition-passing.

`--field NAME=VALUE` builds a minimal condition context, so `explain`/`why-not`
can check real condition behaviour from the command line (mirroring what the
in-process API answers for a live execution).

### Graph

```bash
python -m workflow_kit.cli graph invoice_approval            # DOT
python -m workflow_kit.cli graph invoice_approval --format mermaid
```

## In-process API

All tooling is also available as Python functions, so it can be embedded in a
service layer or test suite:

```python
from workflow_kit import (
    explain,
    parse_workflow_def,
    reachable_states,
    simulate,
    validate_definition,
    why_not,
    to_dot,
    to_mermaid,
)

workflow = parse_workflow_def({...})          # declarative definition

report = validate_definition(workflow)        # ValidationReport
if not report.is_valid:
    for issue in report.errors:
        print(issue.code, issue.message)

result = simulate(workflow, ["submit", "approve"])   # no DB, no audit
print(result.terminal, result.steps)

states = reachable_states(workflow)           # {"draft", "review", ...}
print(to_dot(workflow))                        # Graphviz DOT
print(to_mermaid(workflow))                    # Mermaid flowchart
```

## Testing utilities

`workflow_kit.testing` provides assertion helpers and deterministic fixtures:

```python
from workflow_kit.testing import (
    ExecutionAssertions,
    WorkflowValidationMixin,
    workflow_factory,
)

class InvoiceTests(WorkflowValidationMixin, ExecutionAssertions):
    def test_flow(self):
        workflow = self.assert_valid_workflow(workflow_factory("invoice"))
        # ... start an execution, drive transitions ...
        self.assert_state(execution, "review")
        self.assert_available_actions(execution, ["approve", "reject"], user=user)
        self.assert_can_transition(execution, "approve", user=user)
```

## Structured exceptions

Every `WorkflowError` now carries optional structured context:

- `workflow`, `state`, `action` — the names involved;
- `payload` — a JSON-safe `dict` with machine-readable details.

`WorkflowValidationError.payload["issues"]` is a list of
`{"severity", "code", "message", "location"}` dicts, letting callers render a
report without parsing messages. `SimulationError` and `NoPathFoundError`
cover dry-run failures.