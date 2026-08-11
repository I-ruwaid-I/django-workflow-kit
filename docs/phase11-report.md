# Phase 11 — Developer Experience: Completion Report

**Status:** Implemented, tested, documented, and green across all quality gates.

## Scope

Phase 11 turns Django Workflow Kit from a runtime engine into a well-instrumented
toolkit: static validation with structured reports, declarative definition
parsing, graph introspection and path enumeration, a dry-run simulation engine,
action diagnostics (`explain` / `why-not`), DOT/Mermaid graph rendering, a
`python -m workflow_kit.cli` command line interface, reusable testing utilities
and structured exceptions. Everything except the execution-aware diagnostics is
pure Python and untouched by the database.

## New modules

| Module | Purpose |
| ------ | ------- |
| `engine/validation.py` | `ValidationIssue` / `ValidationReport`, `validate_definition`, `validate_many`; static analysis: reachability, ambiguous routing, self-loops, conditional routing, approvals on terminal states |
| `engine/parse.py` | `parse_workflow_def` — build a `Workflow` from a dict, JSON string, file path or file-like object; reuses the version-snapshot builder for one shared validation path |
| `engine/introspection.py` | `workflow_to_dict` (JSON-safe dump with metrics), `reachable_states`, `simple_paths`, `path_states`, `condition_variants` |
| `engine/simulation.py` | `simulate`, `simulate_all`, `verify_always_completes`; `SimStep` / `SimulationResult`, optional condition `gate` and `max_steps` guard |
| `engine/explain.py` | `explain` / `why_not` returning `ActionExplanation` with per-factor `BlockReason` entries (`no_action`, `terminal`, `permission`, `condition`, `ambiguous`, ...) |
| `graph.py` | `to_dot` (Graphviz) and `to_mermaid` (Mermaid flowchart) plus `render(fmt)` dispatch |
| `cli.py` | `python -m workflow_kit.cli` — `deploy`, `validate`, `view-workflow`, `simulate`, `explain`, `why-not`, `graph` |
| `testing/` | `WorkflowValidationMixin`, `ExecutionAssertions`, `assert_valid`, `workflow_factory`, `SimpleWorkflow`, `workflow_module`, `unregister_all` |

## Structured exceptions

`WorkflowError` gained optional structured context — `workflow`, `state`,
`action` and a JSON-safe `payload` — exposed as instance attributes. New
hierarchy entries:

- `WorkflowValidationError` — raised by `ValidationReport.raise_if_invalid()`;
  `payload["issues"]` carries `{"severity", "code", "message", "location"}`.
- `SimulationError` (base class for dry-run failures) and `NoPathFoundError`
  (raised when not every path can reach a terminal state).

## Command line interface

```bash
python -m workflow_kit.cli view-workflow invoice_approval      # JSON dump
python -m workflow_kit.cli validate  invoice_approval           # static analysis
python -m workflow_kit.cli deploy    path/to/workflows.json     # register/update
python -m workflow_kit.cli simulate  invoice_approval --actions submit,approve
python -m workflow_kit.cli simulate  invoice_approval --all     # enumerate paths
python -m workflow_kit.cli explain   invoice_approval approve --state review
python -m workflow_kit.cli why-not   invoice_approval approve --state review
python -m workflow_kit.cli graph     invoice_approval --format mermaid
```

`deploy` refuses to register an invalid definition (non-zero exit). `simulate`
returns a non-zero exit when an action is blocked. `explain`/`why-not` accept
`--field NAME=VALUE` to build a minimal condition context.

## Demonstration

- `scripts/demo_smoke.py` extended with a **Developer Experience** section:
  validates the demo workflow definition, hands a `SubmissionResult` from the
  validation report, simulates the full approve path, explains an unavailable
  action, and renders the DOT graph — 8 new checks (21 total).

## Testing

| Suite | Result |
| ----- | ------ |
| `tests/test_validation.py` (13 tests) | Valid/invalid definitions, warnings (unreachable, self-loop), conditional-routing info, report summary/payload/locations |
| `tests/test_parse.py` (13 tests) | Dict / JSON string / file / Path loading, name override, label states, conditions + permission, approval requirements, invalid inputs (incl. no-`eval` guard) |
| `tests/test_introspection.py` (10 tests) | JSON-safe dump + metrics, initial/terminal/reachable flags, unreachable reporting, path enumeration to terminals/by end, `path_states`, `max_length` |
| `tests/test_simulation.py` (11 tests) | Full path, blocks on invalid action, gates, `max_steps`, `simulate_all`, `verify_always_completes` (dead-end + closed cycle) |
| `tests/test_explain.py` (10 tests) | Applicable/blocked, terminal, condition pass/fail with blocked-condition names, permission denied/granted/anonymous, `why_not` |
| `tests/test_graph.py` (8 tests) | DOT/Mermaid content, terminals/initial markers, action labels, `render` dispatch + unknown-format error |
| `tests/test_testing.py` (10 tests) | Mixin pass/fail, issue-code filter, execution assertions, factory overrides/registration, `unregister_all` |
| `tests/test_cli.py` (19 tests) | All seven subcommands via `main()`, exit codes, error capture, file and registry sources |
| Full package suite | **393 passed** |
| Coverage (`--source=workflow_kit`, fail-under=90) | **92.0%** |

## Quality gates (all green)

| Gate | Command | Result |
| ---- | ------- | ------ |
| Lint | `ruff check .` | Pass (0 errors) |
| Format | `ruff format --check .` | Pass (135 files) |
| Types | `mypy workflow_kit` | Pass (75 source files) |
| Compile | `python -m compileall -q workflow_kit` | Pass |
| Package tests | `pytest` | **393 passed** |
| Demo smoke | `scripts/demo_smoke.py` | Runs end-to-end incl. Phase 11 checks (21) |
| CLI smoke | `python -m workflow_kit.cli` subcommands | All hand-run against a JSON definition |

## Documentation

- New `docs/tooling.md` — CLI reference, in-process validation/simulation/
  introspection/graph APIs, testing utilities, structured exception payloads;
  linked from `docs/index.md` and `README.md`.
- `docs/index.md` status updated to Phases 1–11 complete.
- `CHANGELOG.md` Phase 11 entry; version bumped to **0.3.0** (package +
  `pyproject.toml` + `tests/test_app.py`).

## Files added/changed this session

- New: `workflow_kit/engine/{validation,parse,introspection,simulation,explain}.py`,
  `workflow_kit/graph.py`, `workflow_kit/cli.py`, `workflow_kit/testing/{__init__,mixins,factories}.py`,
  `tests/test_{validation,parse,introspection,simulation,explain,graph,testing,cli}.py`,
  `docs/tooling.md`, `docs/phase11-report.md`.
- Changed: `workflow_kit/{__init__,exceptions}.py`,
  `workflow_kit/engine/__init__.py`, `pyproject.toml` (0.3.0),
  `scripts/demo_smoke.py`, `docs/index.md`, `README.md`, `CHANGELOG.md`,
  `tests/test_app.py` (0.3.0).

## Recommendation

Phase 11 is complete and all gates pass. Ready for review/commit.