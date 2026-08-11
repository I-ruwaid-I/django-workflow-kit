"""Declarative workflow definitions: :func:`parse_workflow_def`.

Phase 11 makes it possible to describe a workflow with plain data — a Python
``dict`` or a JSON string — instead of only constructing a
:class:`~workflow_kit.engine.workflow.Workflow` object imperatively. This
powers the CLI (``deploy`` / ``validate``), configuration files and quick
prototyping.

Supported shapes (each key optional except ``name``, ``initial`` and
``states``; ``transitions`` defaults to empty):

.. code-block:: python

    parse_workflow_def(
        {
            "name": "invoice_approval",
            "initial": "draft",
            "states": ["draft", "review", "approved"],
            "transitions": [
                ("submit", "draft", "review"),
                {"name": "approve", "source": "review", "target": "approved"},
            ],
        }
    )

Transition dicts accept ``label``, ``permission`` (a string or list of
strings) and ``conditions`` using the same JSON-safe condition encoding as
version snapshots (see :mod:`workflow_kit.engine.versioning`). No ``eval`` or
``exec`` is used anywhere — the definition is purely declarative data.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from workflow_kit.engine.versioning import deserialize_workflow
from workflow_kit.engine.workflow import Workflow
from workflow_kit.exceptions import WorkflowConfigurationError


def _coerce_state(entry: Any) -> dict[str, Any]:
    """Normalize a state entry (string or ``{"name": ..., "label": ...}``)."""
    if isinstance(entry, str):
        return {"name": entry, "label": None}
    if isinstance(entry, Mapping):
        if "name" not in entry:
            raise WorkflowConfigurationError(f"State entry is missing a 'name': {entry!r}")
        return {"name": entry["name"], "label": entry.get("label")}
    raise WorkflowConfigurationError(f"Invalid state entry: {entry!r}")


def _coerce_transition(entry: Any) -> dict[str, Any]:
    """Normalize a transition entry (tuple or mapping).

    Permission, condition and label values are passed through untouched; the
    shared snapshot builder (:func:`deserialize_workflow`) applies the same
    validation and construction rules a version snapshot would receive.
    """
    if isinstance(entry, (list, tuple)) and len(entry) == 3:
        name, source, target = entry
        return {"name": name, "source": source, "target": target}
    if isinstance(entry, Mapping):
        if not all(key in entry for key in ("name", "source", "target")):
            raise WorkflowConfigurationError(f"Transition is missing name/source/target: {entry!r}")
        return {
            "name": entry["name"],
            "source": entry["source"],
            "target": entry["target"],
            "label": entry.get("label"),
            "permission": entry.get("permission"),
            "conditions": list(entry.get("conditions", [])),
        }
    raise WorkflowConfigurationError(f"Invalid transition entry: {entry!r}")


def _normalize_snapshot(data: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a friendly definition dict into a version-snapshot dict.

    The snapshot format is deliberately reused so ``parse_workflow_def`` and
    ``deserialize_workflow`` share one validation path.
    """
    required = ("name", "initial", "states")
    missing = [key for key in required if key not in data]
    if missing:
        raise WorkflowConfigurationError(
            f"Definition is missing required keys: {', '.join(missing)}."
        )
    states = [_coerce_state(entry) for entry in data["states"]]
    transitions = [_coerce_transition(entry) for entry in data.get("transitions", [])]
    snapshot = {
        "name": data["name"],
        "initial": data["initial"],
        "states": states,
        "transitions": transitions,
    }
    requirements = data.get("approval_requirements")
    if requirements:
        snapshot["approval_requirements"] = dict(requirements)
    return snapshot


def _load_data(definition: Any) -> Any:
    """Load a definition from a JSON string or file path/protocol.

    A plain string is treated as inline JSON; a path string, pathlib.Path or
    file-like object (anything accepted by :func:`json.load`) is loaded from
    the file system.
    """
    if isinstance(definition, Path):
        with definition.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    if isinstance(definition, Mapping):
        return dict(definition)
    if isinstance(definition, str):
        stripped = definition.strip()
        path = Path(definition)
        if stripped.startswith("{"):
            return json.loads(definition)
        if path.is_file():
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        raise WorkflowConfigurationError(
            f"Definition string is neither JSON nor an existing file: {definition[:80]!r}."
        )
    return json.load(definition)  # file-like object


def parse_workflow_def(definition: Any, *, name: str | None = None) -> Workflow:
    """Build a (non-registered) ``Workflow`` from declarative ``definition``.

    ``definition`` may be a ``dict``, a JSON string, a file path, a
    :class:`pathlib.Path` or a file-like object. An optional ``name`` overrides
    the ``name`` key inside the definition.

    Raises :class:`WorkflowConfigurationError` for invalid content and
    :class:`~workflow_kit.exceptions.WorkflowVersionError` when a declared
    condition/permission cannot be reconstructed safely.
    """
    data = _load_data(definition)
    if not isinstance(data, Mapping):
        raise WorkflowConfigurationError(
            f"Workflow definition must be a mapping, got {type(data).__name__}."
        )
    if name is not None:
        data = {**data, "name": name}
    snapshot = _normalize_snapshot(data)
    return deserialize_workflow(snapshot)
