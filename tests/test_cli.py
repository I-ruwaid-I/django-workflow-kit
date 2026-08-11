"""Tests for the developer CLI (python -m workflow_kit.cli).

The CLI is pure Python and never touches the database; these tests drive its
``main()`` function against definitions passed as registered workflows or as
temporary JSON files.
"""

import json

import pytest
from workflow_kit import Workflow
from workflow_kit.cli import main
from workflow_kit.engine import registry
from workflow_kit.exceptions import WorkflowNotFoundError


def _register_demo() -> str:
    name = "cli_demo"
    registry.unregister(name)
    registry.register(
        Workflow(
            name=name,
            initial="draft",
            states=["draft", "review", "approved", "rejected"],
            transitions=[
                ("submit", "draft", "review"),
                ("approve", "review", "approved"),
                ("reject", "review", "rejected"),
            ],
            register=False,
        )
    )
    return name


def _write_json(tmp_path, data) -> str:
    path = tmp_path / "wf.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# -- view-workflow ------------------------------------------------------------


def test_view_workflow_registered(tmp_path, capsys):
    _register_demo()
    code = main(["view-workflow", "cli_demo"])
    assert code == 0
    output = capsys.readouterr().out
    assert '"name": "cli_demo"' in output


def test_view_workflow_from_file(tmp_path, capsys):
    path = _write_json(
        tmp_path,
        {
            "name": "file_demo",
            "initial": "a",
            "states": ["a", "b"],
            "transitions": [("go", "a", "b")],
        },
    )
    code = main(["view-workflow", path])
    assert code == 0
    assert '"name": "file_demo"' in capsys.readouterr().out


def test_view_workflow_missing_returns_error(tmp_path, capsys):
    code = main(["view-workflow", "no_such_workflow"])
    assert code != 0


# -- validate ----------------------------------------------------------------


def test_validate_registered(tmp_path, capsys):
    _register_demo()
    code = main(["validate", "--name", "cli_demo"])
    assert code == 0
    assert "0 error(s)" in capsys.readouterr().out


def test_validate_file(tmp_path, capsys):
    path = _write_json(
        tmp_path,
        {
            "name": "file_demo",
            "initial": "a",
            "states": ["a", "b"],
            "transitions": [("go", "a", "b")],
        },
    )
    code = main(["validate", path])
    assert code == 0


def test_validate_reports_errors_and_exit_code(tmp_path, capsys):
    path = _write_json(
        tmp_path,
        {
            "name": "bad_demo",
            "initial": "a",
            "states": ["a", "b", "c"],
            "transitions": [("go", "a", "b"), ("go", "a", "c")],
        },
    )
    code = main(["validate", path])
    assert code == 1
    assert "ERROR" in capsys.readouterr().out


# -- simulate ----------------------------------------------------------------


def test_simulate_actions(tmp_path, capsys):
    _register_demo()
    code = main(["simulate", "cli_demo", "--actions", "submit,approve"])
    assert code == 0
    output = capsys.readouterr().out
    assert "Reached 'approved'" in output


def test_simulate_blocked_action_exit_code(tmp_path, capsys):
    _register_demo()
    code = main(["simulate", "cli_demo", "--actions", "submit,submit"])
    assert code == 1
    assert "Blocked at action" in capsys.readouterr().out


def test_simulate_all(tmp_path, capsys):
    _register_demo()
    code = main(["simulate", "cli_demo", "--all"])
    assert code == 0
    assert "2 path(s)" in capsys.readouterr().out


# -- explain / why-not --------------------------------------------------------


def test_explain_applicable(tmp_path, capsys):
    _register_demo()
    code = main(["explain", "cli_demo", "approve", "--state", "review"])
    assert code == 0
    assert "APPLICABLE" in capsys.readouterr().out


def test_explain_blocked_action(tmp_path, capsys):
    _register_demo()
    code = main(["explain", "cli_demo", "approve", "--state", "draft"])
    assert code == 1
    assert "NOT APPLICABLE" in capsys.readouterr().out


def test_why_not_reports_reasons(tmp_path, capsys):
    _register_demo()
    code = main(["why-not", "cli_demo", "approve", "--state", "draft"])
    assert code == 1
    output = capsys.readouterr().out
    assert "NOT APPLICABLE" in output
    assert "no_action" in output


# -- graph --------------------------------------------------------------------


def test_graph_dot(tmp_path, capsys):
    _register_demo()
    code = main(["graph", "cli_demo"])
    assert code == 0
    assert capsys.readouterr().out.startswith("digraph")


def test_graph_mermaid(tmp_path, capsys):
    _register_demo()
    code = main(["graph", "cli_demo", "--format", "mermaid"])
    assert code == 0
    assert capsys.readouterr().out.startswith("flowchart")


def test_graph_unknown_format_returns_error(tmp_path, capsys):
    _register_demo()
    code = main(["graph", "cli_demo", "--format", "svg"])
    assert code != 0


# -- deploy -------------------------------------------------------------------


def test_deploy_from_json(tmp_path):
    path = _write_json(
        tmp_path,
        {
            "name": "deploy_demo",
            "initial": "a",
            "states": ["a", "b"],
            "transitions": [("go", "a", "b")],
        },
    )
    registry.unregister("deploy_demo")
    code = main(["deploy", path])
    assert code == 0
    assert registry.get_workflow("deploy_demo").initial == "a"
    registry.unregister("deploy_demo")


def test_deploy_no_register(tmp_path, capsys):
    path = _write_json(
        tmp_path,
        {
            "name": "no_reg",
            "initial": "a",
            "states": ["a", "b"],
            "transitions": [("go", "a", "b")],
        },
    )
    registry.unregister("no_reg")
    code = main(["deploy", path, "--no-register"])
    assert code == 0
    with pytest.raises(WorkflowNotFoundError):
        registry.get_workflow("no_reg")
    registry.unregister("no_reg")


# -- error handling -----------------------------------------------------------


def test_unknown_command_returns_error(capsys):
    code = main(["not-a-command"])
    assert code != 0


def test_missing_command_prints_help(capsys):
    code = main([])
    assert code != 0
    captured = capsys.readouterr()
    assert "usage" in (captured.out + captured.err).lower()
