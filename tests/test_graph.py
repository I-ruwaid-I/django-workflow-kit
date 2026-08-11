"""Unit tests for graph rendering (DOT and Mermaid)."""

import pytest
from workflow_kit import Workflow, render_graph, to_dot, to_mermaid


def _workflow():
    return Workflow(
        name="graph_demo",
        register=False,
        initial="draft",
        states=["draft", "review", "approved"],
        transitions=[
            ("submit", "draft", "review"),
            ("approve", "review", "approved"),
        ],
    )


def test_dot_starts_with_digraph():
    assert to_dot(_workflow()).startswith("digraph graph_demo {")


def test_dot_contains_edges():
    dot = to_dot(_workflow())
    assert "draft -> review" in dot
    assert "review -> approved" in dot


def test_dot_flags_terminal_and_initial():
    dot = to_dot(_workflow())
    assert "doublecircle" in dot
    assert "lightgreen" in dot


def test_dot_labels_edges_with_action():
    dot = to_dot(_workflow())
    assert "Submit" in dot
    assert "Approve" in dot


def test_mermaid_contains_flowchart():
    mermaid_graph = to_mermaid(_workflow())
    assert mermaid_graph.startswith("flowchart LR")
    assert "draft -->|Submit| review" in mermaid_graph


def test_mermaid_stadium_for_terminal():
    mermaid_graph = to_mermaid(_workflow())
    assert "approved([" in mermaid_graph


def test_render_dispatches_formats():
    assert render_graph(_workflow(), "dot").startswith("digraph")
    assert render_graph(_workflow(), "mermaid").startswith("flowchart")


def test_render_unknown_format_raises():
    with pytest.raises(ValueError):
        render_graph(_workflow(), "png")
