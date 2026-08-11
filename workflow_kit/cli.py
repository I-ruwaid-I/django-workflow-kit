"""Command-line interface for Django Workflow Kit.

Phase 11 ships ``python -m workflow_kit.cli`` so developers can inspect and
exercise workflow definitions without writing Python:

- ``deploy`` — register/update one or more workflow definitions from a JSON
  file or a Python module exposing ``WORKFLOWS``.
- ``validate`` — statically analyse registered or declared workflows.
- ``view-workflow`` — dump a full description of a definition as JSON.
- ``simulate`` — dry-run a sequence of actions, or enumerate every path.
- ``explain`` / ``why-not`` — diagnose whether an action can run.
- ``graph`` — render a definition as DOT or Mermaid.

The CLI is intentionally pure Python: it never calls ``django.setup()`` or
touches the database. Execution-level questions (``explain``/``why-not``) are
answered with a declared current state and optional object fields, mirroring
what the in-process API answers for a real execution.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Sequence
from typing import Any

from workflow_kit.engine import registry
from workflow_kit.engine.explain import explain
from workflow_kit.engine.introspection import workflow_to_dict
from workflow_kit.engine.parse import parse_workflow_def
from workflow_kit.engine.simulation import simulate, simulate_all
from workflow_kit.engine.validation import (
    ValidationReport,
    validate_definition,
    validate_many,
)
from workflow_kit.engine.workflow import Workflow
from workflow_kit.exceptions import (
    NoPathFoundError,
    WorkflowError,
    WorkflowNotFoundError,
    WorkflowVersionError,
)
from workflow_kit.graph import render

_EXIT_OK = 0
_EXIT_ERROR = 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m workflow_kit.cli",
        description="Django Workflow Kit developer CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    deploy = subparsers.add_parser(
        "deploy", help="Register workflow definitions from a file or module."
    )
    deploy.add_argument("source", help="Path to a JSON file or importable module path.")
    deploy.add_argument(
        "--no-register",
        action="store_true",
        help="Validate the definition without registering it.",
    )
    deploy.set_defaults(func=_cmd_deploy)

    validate = subparsers.add_parser(
        "validate", help="Validate workflow definitions (registered or declared)."
    )
    validate.add_argument("source", nargs="?", help="Optional JSON file or module path.")
    validate.add_argument("--name", help="Validate only this registered workflow.")
    validate.set_defaults(func=_cmd_validate)

    view = subparsers.add_parser("view-workflow", help="Dump a workflow definition as JSON.")
    view.add_argument("name", nargs="?", help="Registered workflow name or file path.")
    view.set_defaults(func=_cmd_view)

    simulate = subparsers.add_parser(
        "simulate", help="Dry-run a workflow without touching the database."
    )
    simulate.add_argument("name", nargs="?", help="Registered workflow name or file path.")
    simulate.add_argument("--actions", help="Comma-separated actions to apply.")
    simulate.add_argument("--all", action="store_true", help="Enumerate every path.")
    simulate.add_argument("--start", help="Start state (defaults to initial).")
    simulate.set_defaults(func=_cmd_simulate)

    explain = subparsers.add_parser(
        "explain", help="Explain whether an action can run from a state."
    )
    explain.add_argument("name", help="Registered workflow name or file path.")
    explain.add_argument("action", help="The action to explain.")
    explain.add_argument("--state", help="Current state (defaults to initial).")
    explain.add_argument(
        "--field",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Object field to include in the condition context (repeatable).",
    )
    explain.set_defaults(func=_cmd_explain)

    why_not = subparsers.add_parser(
        "why-not", help="Report why an action cannot execute from a state."
    )
    why_not.add_argument("name", help="Registered workflow name or file path.")
    why_not.add_argument("action", help="The action to explain.")
    why_not.add_argument("--state", help="Current state (defaults to initial).")
    why_not.add_argument(
        "--field",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Object field to include in the condition context (repeatable).",
    )
    why_not.set_defaults(func=_cmd_why_not)

    graph = subparsers.add_parser("graph", help="Render a workflow definition as DOT or Mermaid.")
    graph.add_argument("name", help="Registered workflow name or file path.")
    graph.add_argument("--format", choices=["dot", "mermaid"], default="dot", help="Output format.")
    graph.set_defaults(func=_cmd_graph)

    return parser


def _load(source: str) -> Workflow:
    """Resolve a workflow from a registered name or a file path."""
    try:
        return registry.get_workflow(source)
    except WorkflowNotFoundError:
        return parse_workflow_def(source)


def _load_many(source: str) -> list[Workflow]:
    """Load one or more workflows from a JSON file or Python module."""
    if source.rstrip().endswith(".json") or not source.replace("_", ".").isidentifier():
        return [parse_workflow_def(source)]

    module = importlib.import_module(source)
    candidates: list[Any] = []
    for attr in ("WORKFLOWS", "workflows", "WORKFLOW"):
        value = getattr(module, attr, None)
        if value is not None:
            candidates.extend(value if isinstance(value, (list, tuple)) else [value])
    if not candidates:
        raise WorkflowError(f"Module '{source}' does not expose WORKFLOWS/workflows/WORKFLOW.")
    return candidates


def _render_report(report: ValidationReport) -> str:
    lines = [f"Workflow '{report.workflow_name}':"]
    summary = report.summary()
    lines.append(
        f"  {summary['errors']} error(s), {summary['warnings']} warning(s), {summary['info']} info."
    )
    for issue in report.issues:
        prefix = {"error": "ERROR", "warning": "WARN", "info": "INFO"}[issue.severity]
        location = f" [{issue.location}]" if issue.location else ""
        lines.append(f"  {prefix}: {issue.message}{location}")
    return "\n".join(lines)


# -- Subcommand implementations -----------------------------------------------


def _cmd_deploy(args: argparse.Namespace) -> int:
    failed = False
    for workflow in _load_many(args.source):
        report = validate_definition(workflow)
        print(_render_report(report))
        if not report.is_valid:
            failed = True
            continue
        if not args.no_register:
            registry.unregister(workflow.name)
            registry.register(workflow)
            print(
                f"Deployed '{workflow.name}' ({len(workflow.states)} states, "
                f"{_transition_count(workflow)} transitions)."
            )
    return _EXIT_ERROR if failed else _EXIT_OK


def _transition_count(workflow: Workflow) -> int:
    return sum(len(workflow.transitions_from(state.name)) for state in workflow.states)


def _cmd_validate(args: argparse.Namespace) -> int:
    reports: dict[str, ValidationReport]
    if args.name:
        workflow = registry.get_workflow(args.name)
        reports = {workflow.name: validate_definition(workflow)}
    elif args.source:
        workflows = _load_many(args.source)
        reports = validate_many(workflows)
    else:
        reports = validate_many(list(registry.all_workflows()))
        if not reports:
            print("No workflows are registered.")
            return _EXIT_OK
    failed = False
    for report in reports.values():
        print(_render_report(report))
        failed = failed or not report.is_valid
    return _EXIT_ERROR if failed else _EXIT_OK


def _cmd_view(args: argparse.Namespace) -> int:
    workflow = _load(args.name)
    print(json.dumps(workflow_to_dict(workflow), indent=2, default=str))
    return _EXIT_OK


def _cmd_simulate(args: argparse.Namespace) -> int:
    workflow = _load(args.name)
    start = args.start or workflow.initial
    if args.all:
        results = simulate_all(workflow, start=start)
        print(f"{len(results)} path(s) from '{start}':")
        for index, result in enumerate(results, start=1):
            action_str = " -> ".join(step.action for step in result.steps) or "(no action)"
            print(f"  {index}. {action_str}  -> {result.terminal}")
        return _EXIT_OK
    actions = [a.strip() for a in args.actions.split(",")] if args.actions else []
    result = simulate(workflow, actions, start=start)
    for step in result.steps:
        print(f"  {step}")
    if result.blocked:
        print(f"Blocked at action '{result.blocked}' (state '{result.terminal}').")
        return _EXIT_ERROR
    print(f"Reached '{result.terminal}'.")
    return _EXIT_OK


def _field_context(fields: Sequence[str], current_state: str) -> tuple[Any, dict[str, Any]]:
    """Build a minimal (execution, object-fields) pair from NAME=VALUE pairs."""
    object_data: dict[str, Any] = {}
    for field in fields:
        name, sep, value = field.partition("=")
        if not sep:
            raise WorkflowError(f"--field expects NAME=VALUE, got '{field}'.")
        object_data[name.strip()] = value

    class _Stub:
        def __init__(self, state: str) -> None:
            self.current_state = state

    return _Stub(current_state), object_data


class _StubContext:
    """A condition context whose ``object`` exposes the declared fields."""

    def __init__(self, object_data: dict[str, Any]) -> None:
        self.object = _FieldBag(object_data)


class _FieldBag:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        try:
            return self._data[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _cmd_explain(args: argparse.Namespace) -> int:
    workflow = _load(args.name)
    state = args.state or workflow.initial
    execution, object_data = _field_context(args.field, state)
    context = _StubContext(object_data)
    explanation = explain(workflow, execution, args.action, condition_context=context)
    print(f"Workflow '{workflow.name}' state '{state}' action '{args.action}':")
    if explanation.applicable:
        print("  APPLICABLE")
        return _EXIT_OK
    print("  NOT APPLICABLE")
    for reason in explanation.reasons:
        print(f"    - [{reason.kind}] {reason.detail}")
    return _EXIT_ERROR


def _cmd_why_not(args: argparse.Namespace) -> int:
    return _cmd_explain(args)


def _cmd_graph(args: argparse.Namespace) -> int:
    workflow = _load(args.name)
    try:
        print(render(workflow, args.format))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return _EXIT_ERROR
    return _EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse calls sys.exit() for missing commands / --help / usage
        # errors; propagate its exit code cleanly.
        return int(exc.code) if isinstance(exc.code, int) else _EXIT_ERROR
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return _EXIT_ERROR
    try:
        code = func(args)
        return int(code) if isinstance(code, int) else _EXIT_OK
    except (WorkflowError, WorkflowVersionError, NoPathFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return _EXIT_ERROR
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return _EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
