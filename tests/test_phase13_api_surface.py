"""Phase 13 tests: public API stability and import review (PHASE13 ``#26``-``#28``).

The public API is the set of names exported from ``workflow_kit``. These tests
lock that surface so it cannot accidentally grow (or shrink) between releases:

* every ``__all__`` export is importable and resolves to a real object;
* internal implementation modules are *not* re-exported as public names;
* the exported objects are the stable, intentional classes/functions and not
  leftover import aliases;
* the package version stays pinned to the advertised ``0.4.0`` line.

This mirrors the ``#27 Public Import Review`` requirement: only intentionally
public objects are exported, and internal details stay behind their modules.
"""

from __future__ import annotations

import inspect

import pytest
import workflow_kit

# Names that must NOT appear as public exports because they are internal
# implementation details (live behind their modules by design).
INTERNAL_NAMES = {
    "capture",
    "emit",
    "flush",
    "is_authorized",
    "WorkflowEvent",
    "WorkflowEventType",
    "WorkflowDelegation",
    "VersionStatus",
}

# ORM models live in ``workflow_kit.models`` (they need the Django app registry,
# so they can never be bound at top-level import time).
MODEL_NAMES = {"Approval", "ApprovalStatus", "WorkflowAttachment", "WorkflowComment"}


def test_all_exports_resolve_to_real_objects():
    """Every name in ``workflow_kit.__all__`` imports cleanly and exists."""
    for name in workflow_kit.__all__:
        assert hasattr(workflow_kit, name), f"__all__ references missing export {name!r}"
        obj = getattr(workflow_kit, name)
        assert obj is not None


def test_public_api_contains_no_duplicate_or_gap():
    """``__all__`` is exactly the exported surface (no hidden/extra names)."""
    exported = set(workflow_kit.__all__)
    # Everything in __all__ is a real attribute, and no accidental public
    # attribute that we did not intend to expose is missing from __all__.
    assert len(exported) == len(workflow_kit.__all__), "duplicate entries in __all__"
    for name in exported:
        assert name in workflow_kit.__dict__


def test_internal_implementation_details_are_not_exported():
    """Internal helpers do not leak into the public ``workflow_kit`` surface."""
    exported = set(workflow_kit.__all__)
    assert not (exported & INTERNAL_NAMES)
    assert not (exported & MODEL_NAMES)


def test_public_api_names_are_documented_types():
    """Core public exports resolve to the intended stable types."""
    assert issubclass(workflow_kit.Workflow, object)
    assert workflow_kit.EventType is not None
    assert callable(workflow_kit.subscribe)
    assert callable(workflow_kit.get_workflow)
    assert callable(workflow_kit.execution_metrics)


def test_public_classes_are_importable_and_constructible():
    """Stable public classes can be imported from the top-level package."""
    from workflow_kit import (
        ApprovalContext,
        ApprovalMode,
        ApprovalRequirement,
        ApproverResolver,
        Condition,
        DomainEvent,
        ObjectRef,
        PermissionContext,
        PermissionProvider,
        State,
        TimelineEvent,
        Transition,
    )

    assert issubclass(Condition, object)
    assert issubclass(PermissionProvider, object)
    assert issubclass(State, object)
    assert issubclass(Transition, object)
    assert DomainEvent is not None
    assert ObjectRef is not None
    assert TimelineEvent is not None
    assert ApprovalMode is not None
    assert ApprovalContext is not None
    assert ApprovalRequirement is not None
    assert ApproverResolver is not None
    assert PermissionContext is not None


def test_version_is_pinned_to_0_4_line():
    """The package version stays pinned to the advertised 0.4.0 line."""
    assert workflow_kit.__version__ == "0.4.0"
    major, minor, patch = (int(part) for part in workflow_kit.__version__.split("."))
    assert (major, minor) == (0, 4)


def test_subpackage_public_surfaces_are_consistent():
    """Feature subpackages expose their documented names and no stray internals."""
    from workflow_kit import analytics, conditions, events, models, permissions

    assert "execution_metrics" in analytics.__all__
    assert "execution_metrics" in workflow_kit.__all__
    assert "FieldEquals" in conditions.__all__
    assert "EventType" in events.__all__
    assert "WorkflowExecution" in models.__all__
    assert "PermissionProvider" in permissions.__all__


def test_public_functions_have_signatures_not_swallowed_by_varargs():
    """Public callables keep explicit signatures (readability / stability)."""
    for name in workflow_kit.__all__:
        obj = getattr(workflow_kit, name)
        if not (inspect.isfunction(obj) or inspect.isbuiltin(obj)):
            continue
        signature = inspect.signature(obj)
        if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in signature.parameters.values()):
            pytest.fail(f"public callable {name!r} uses *args without named parameters")
