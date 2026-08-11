"""Graph rendering for workflow definitions.

Phase 11 adds :func:`to_dot` and :func:`to_mermaid` so definitions can be
visualized with Graphviz, Mermaid or any renderer that understands those
formats. Both outputs are derived purely from the definition — no database —
and label edges with the transition action (and which conditions / permission
requirements apply).
"""

from __future__ import annotations

from workflow_kit.engine.workflow import Transition, Workflow


def _clean(name: str) -> str:
    """Make a state name safe as a node identifier in both formats."""
    return name.replace(" ", "_").replace("-", "_")


def _transition_annotation(transition: Transition) -> str:
    """Build a short human annotation describing a transition edge."""
    parts = [transition.label or transition.name]
    if transition.conditions:
        parts.append("conditions: " + ", ".join(type(c).__name__ for c in transition.conditions))
    if transition.permission:
        parts.append(f"permission: {transition.permission}")
    return "\\n".join(parts)


def to_dot(workflow: Workflow) -> str:
    """Render ``workflow`` as a Graphviz DOT ``digraph``.

    The initial state is drawn in green, terminal states in double circles, and
    edges carry the action label plus any condition/permission annotation.
    """
    lines = [f"digraph {_clean(workflow.name)} {{", "  rankdir=LR;", "  node [shape=ellipse];"]
    for state in workflow.states:
        attributes = {}
        if state.name == workflow.initial:
            attributes["style"] = "filled"
            attributes["fillcolor"] = "lightgreen"
        if workflow.is_terminal(state.name):
            attributes["shape"] = "doublecircle"
        label = workflow.state(state.name).label
        if attributes:
            attr_text = ", ".join(f"{k}={v!r}" for k, v in attributes.items())
            lines.append(f"  {_clean(state.name)} [label={label!r} {attr_text}];")
        else:
            lines.append(f"  {_clean(state.name)} [label={label!r}];")
    for transition in _ordered_transitions(workflow):
        source = _clean(transition.source)
        target = _clean(transition.target)
        annotation = _transition_annotation(transition).replace('"', '\\"')
        lines.append(f"  {source} -> {target} [label={annotation!r}];")
    lines.append("}")
    return "\n".join(lines)


def to_mermaid(workflow: Workflow) -> str:
    """Render ``workflow`` as a Mermaid ``flowchart``.

    Terminal states are drawn with the ``([...])`` stadium shape, the initial
    state is annotated with ``((...))``, and edges are labeled with the action.
    """
    lines = [
        "flowchart LR",
        f"    START(( )) --> {_clean(workflow.initial)}",
    ]
    for state in workflow.states:
        name = _clean(state.name)
        label = workflow.state(state.name).label
        if workflow.is_terminal(state.name):
            lines.append(f"    {name}([{label!r}])")
        else:
            lines.append(f"    {name}[{label!r}]")
    for transition in _ordered_transitions(workflow):
        source = _clean(transition.source)
        target = _clean(transition.target)
        annotation = _transition_annotation(transition).replace("\\n", "<br/>")
        lines.append(f"    {source} -->|{annotation}| {target}")
    return "\n".join(lines)


def _ordered_transitions(workflow: Workflow) -> list[Transition]:
    """All transitions in definition order, deduplicated."""
    ordered: list[Transition] = []
    seen: set[tuple[str, str, str]] = set()
    for state in workflow.states:
        for transition in workflow.transitions_from(state.name):
            key = (transition.source, transition.name, transition.target)
            if key not in seen:
                seen.add(key)
                ordered.append(transition)
    return ordered


def render(workflow: Workflow, fmt: str = "dot") -> str:
    """Render ``workflow`` as ``dot`` or ``mermaid``.

    Raises :class:`ValueError` for unsupported formats.
    """
    if fmt == "dot":
        return to_dot(workflow)
    if fmt == "mermaid":
        return to_mermaid(workflow)
    raise ValueError(f"Unsupported graph format '{fmt}'; use 'dot' or 'mermaid'.")
