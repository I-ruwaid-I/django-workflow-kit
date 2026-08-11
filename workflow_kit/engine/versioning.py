"""Workflow versioning: immutable versions, serialization and version binding.

Phase 9 separates *workflow identity* (the registered ``Workflow``, referenced
by name) from *definition version* (a numbered :class:`WorkflowVersion` row
holding a JSON snapshot of the definition).

The rule enforced here is: **an execution binds exactly one version at start
and never changes it.** Every resolution for a bound execution — states,
transitions, conditions, approvals, permissions — reads the reconstructed
definition of that version rather than the live registered one.

Definitions are stored as JSON snapshots. Only snapshots that can be rebuilt
safely are eligible: built-in conditions, string permission specs and string
approver assignments serialize; custom condition classes, callable/PermissionProvider
permissions and callable approvers do not, and such workflows keep the
legacy, definition-in-Python behaviour with no version binding.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, transaction

from workflow_kit.approvals.requirements import (
    ApprovalMode,
    ApprovalRequirement,
)
from workflow_kit.conditions.builtin import (
    FieldEquals,
    FieldNotEquals,
    GreaterThan,
    GreaterThanOrEqual,
    IsFalse,
    IsTrue,
    LessThan,
    LessThanOrEqual,
)
from workflow_kit.conditions.logical import All, Not
from workflow_kit.conditions.logical import Any as AnyCond
from workflow_kit.engine.workflow import State, Transition, Workflow
from workflow_kit.exceptions import (
    WorkflowConfigurationError,
    WorkflowNotFoundError,
    WorkflowVersionError,
)

if TYPE_CHECKING:
    from workflow_kit.models.execution import WorkflowExecution
    from workflow_kit.models.version import WorkflowVersion

# Version cache: {pk: (updated_at, Workflow)} so DRAFT edits invalidate on save.
_VERSION_CACHE: dict[int, tuple[Any, Workflow]] = {}


def _invalidate_version_cache(pk: int | None) -> None:
    if pk is None:
        _VERSION_CACHE.clear()
        return
    _VERSION_CACHE.pop(pk, None)


# -- JSON value encoding -----------------------------------------------------


def _encode_value(value: Any) -> Any:
    """Encode a condition/value so it survives JSON storage losslessly."""
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, timedelta):
        return {
            "$timedelta": {
                "days": value.days,
                "seconds": value.seconds,
                "microseconds": value.microseconds,
            }
        }
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, (list, tuple)):
        return [_encode_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode_value(val) for key, val in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise WorkflowVersionError(
        f"Value of type {type(value).__name__} cannot be stored in a workflow version snapshot."
    )


def _decode_value(value: Any) -> Any:
    """Inverse of :func:`_encode_value`."""
    if isinstance(value, dict):
        if "$decimal" in value:
            return Decimal(value["$decimal"])
        if "$timedelta" in value:
            return timedelta(**value["$timedelta"])
        if "$datetime" in value:
            return datetime.fromisoformat(value["$datetime"])
        return {key: _decode_value(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    return value


# -- Condition (de)serialization --------------------------------------------


_BUILTIN_CONDITIONS = {
    "field_equals": ("field", FieldEquals),
    "field_not_equals": ("field", FieldNotEquals),
    "greater_than": ("field", GreaterThan),
    "greater_than_or_equal": ("field", GreaterThanOrEqual),
    "less_than": ("field", LessThan),
    "less_than_or_equal": ("field", LessThanOrEqual),
    "is_true": ("field", IsTrue),
    "is_false": ("field", IsFalse),
}


def _condition_to_dict(condition: Any) -> dict[str, Any]:
    if isinstance(condition, All):
        return {"type": "all", "conditions": [_condition_to_dict(c) for c in condition.conditions]}
    if isinstance(condition, AnyCond):
        return {"type": "any", "conditions": [_condition_to_dict(c) for c in condition.conditions]}
    if isinstance(condition, Not):
        if len(condition.conditions) != 1:
            raise WorkflowVersionError("Cannot serialize a Not condition without a single child.")
        return {
            "type": "not",
            "condition": _condition_to_dict(condition.conditions[0]),
        }
    for tag, (attr, _cls) in _BUILTIN_CONDITIONS.items():
        if type(condition) is _cls:  # noqa: PLC0121 - exact built-in class
            if tag in ("is_true", "is_false"):
                return {"type": tag, "field": getattr(condition, attr)}
            return {
                "type": tag,
                "field": getattr(condition, attr),
                "value": _encode_value(condition.value),
            }
    raise WorkflowVersionError(
        f"Condition of type {type(condition).__name__} cannot be stored in a "
        "workflow version snapshot."
    )


def _condition_from_dict(data: dict[str, Any]) -> Any:
    kind = data.get("type")
    if kind in ("all", "any"):
        children = [_condition_from_dict(item) for item in data["conditions"]]
        return All(*children) if kind == "all" else AnyCond(*children)
    if kind == "not":
        return Not(_condition_from_dict(data["condition"]))
    if kind not in _BUILTIN_CONDITIONS:
        raise WorkflowVersionError(f"Unknown condition type '{kind}' in version snapshot.")
    if kind in ("is_true", "is_false"):
        return _BUILTIN_CONDITIONS[kind][1](data["field"])
    return _BUILTIN_CONDITIONS[kind][1](data["field"], _decode_value(data["value"]))


# -- Permission (de)serialization -------------------------------------------


def _permission_to_json(permission: Any) -> Any:
    """Serialize a permission spec; only declarative forms are allowed."""
    if permission is None or isinstance(permission, str):
        return permission
    if isinstance(permission, (list, tuple)):
        for item in permission:
            if not isinstance(item, str):
                raise WorkflowVersionError(
                    "Permissions backed by PermissionProvider or callables cannot "
                    "be stored in a version snapshot."
                )
        return list(permission)
    raise WorkflowVersionError(
        "Permissions backed by PermissionProvider or callables cannot be stored "
        "in a workflow version snapshot."
    )


def _permission_from_json(data: Any) -> Any:
    return data


# -- Approval requirement (de)serialization ---------------------------------


def _requirement_to_dict(requirement: ApprovalRequirement) -> dict[str, Any]:
    for approver in requirement.approvers:
        if not isinstance(approver, str):
            raise WorkflowVersionError(
                "Approval requirements backed by resolvers, callables or user "
                "instances cannot be stored in a version snapshot."
            )
    return {
        "mode": requirement.mode,
        "approvers": list(requirement.approvers),
        "quorum": requirement.quorum,
        "allow_self": requirement.allow_self,
        "sla": _encode_value(requirement.sla),
        "label": requirement.label,
        "metadata": _encode_value(requirement.metadata),
    }


def _requirement_from_dict(data: dict[str, Any]) -> ApprovalRequirement:
    return ApprovalRequirement(
        mode=data.get("mode", ApprovalMode.ALL),
        approvers=tuple(data.get("approvers", [])),
        quorum=data.get("quorum", 1),
        allow_self=data.get("allow_self", True),
        sla=_decode_value(data.get("sla")),
        label=data.get("label", ""),
        metadata=_decode_value(data.get("metadata", {})),
    )


# -- Workflow (de)serialization ---------------------------------------------


def _transition_to_dict(transition: Transition) -> dict[str, Any]:
    return {
        "name": transition.name,
        "source": transition.source,
        "target": transition.target,
        "label": transition.label,
        "permission": _permission_to_json(transition.permission),
        "conditions": [_condition_to_dict(c) for c in transition.conditions],
    }


def serialize_workflow(workflow: Workflow) -> dict[str, Any]:
    """Return the JSON-safe snapshot of ``workflow``.

    Raises :class:`~workflow_kit.exceptions.WorkflowVersionError` when the
    definition uses elements that cannot be represented safely in JSON
    (custom conditions, callable permissions, dynamic approvers).
    """
    requirements: dict[str, Any] = {}
    for state, requirement in workflow.approval_requirements.items():
        requirements[state] = _requirement_to_dict(requirement)
    return {
        "name": workflow.name,
        "initial": workflow.initial,
        "states": [{"name": s.name, "label": s.label} for s in workflow.states],
        "transitions": [_transition_to_dict(t) for t in _workflow_transitions(workflow)],
        "approval_requirements": requirements,
    }


def _workflow_transitions(workflow: Workflow) -> list[Transition]:
    """All transitions in definition order (source maps preserve order)."""
    ordered: list[Transition] = []
    seen: set[tuple[str, str, str]] = set()
    for transitions in workflow._transitions_by_source.values():  # noqa: SLF001
        for transition in transitions:
            key = (transition.source, transition.name, transition.target)
            if key not in seen:
                seen.add(key)
                ordered.append(transition)
    return ordered


def deserialize_workflow(snapshot: dict[str, Any]) -> Workflow:
    """Rebuild a ``Workflow`` from a version snapshot.

    The snapshot is validated with the same eager rules as a hand-written
    definition; invalid content raises
    :class:`~workflow_kit.exceptions.WorkflowVersionError`.
    """
    try:
        states = [State(name=s["name"], label=s["label"]) for s in snapshot["states"]]
        transitions = [
            Transition(
                t["name"],
                t["source"],
                t["target"],
                label=t.get("label"),
                permission=_permission_from_json(t.get("permission")),
                conditions=[_condition_from_dict(c) for c in t.get("conditions", [])],
            )
            for t in snapshot["transitions"]
        ]
        requirements = {
            state: _requirement_from_dict(data)
            for state, data in snapshot.get("approval_requirements", {}).items()
        }
        return Workflow(
            name=snapshot["name"],
            initial=snapshot["initial"],
            states=states,
            transitions=transitions,
            approval_requirements=requirements or None,
            register=False,
        )
    except WorkflowVersionError:
        raise
    except (KeyError, TypeError, ValueError, WorkflowConfigurationError) as exc:
        raise WorkflowVersionError(f"Invalid workflow version snapshot: {exc}") from exc


# -- Version -> Workflow resolution -----------------------------------------


def get_version_workflow(version: WorkflowVersion) -> Workflow:
    """Resolve the :class:`Workflow` definition stored in ``version``.

    Reconstruction results are cached per version and keyed by its
    ``updated_at`` so edits to a draft are picked up without invalidation hooks.
    """
    from workflow_kit.models.version import WorkflowVersion

    if not isinstance(version, WorkflowVersion):
        pk = version
        version = WorkflowVersion.objects.filter(pk=pk).first()
        if version is None:
            raise WorkflowNotFoundError(f"No workflow version with pk {pk} exists.")
        cached = _VERSION_CACHE.get(version.pk)
    else:
        cached = _VERSION_CACHE.get(version.pk)
    if cached is not None and cached[0] == version.updated_at:
        return cached[1]
    workflow = deserialize_workflow(version.definition)
    _VERSION_CACHE[version.pk] = (version.updated_at, workflow)
    return workflow


def get_workflow_for_execution(execution: WorkflowExecution) -> Workflow:
    """Resolve the definition an execution must use.

    Version-bound executions use their immutable version; legacy (unversioned)
    executions keep the live registered definition.
    """
    from workflow_kit.engine.registry import get_workflow

    if getattr(execution, "workflow_version_id", None) and execution.workflow_version is not None:
        return get_version_workflow(execution.workflow_version)
    return get_workflow(execution.workflow_name)


# -- Version lifecycle -------------------------------------------------------


def active_version(workflow_name: str) -> WorkflowVersion | None:
    """Return the active (highest published) version of ``workflow_name``."""
    from workflow_kit.models.version import VersionStatus, WorkflowVersion

    return (
        WorkflowVersion.objects.filter(
            workflow=workflow_name,
            status=VersionStatus.PUBLISHED,
        )
        .order_by("-version")
        .first()
    )


def ensure_workflow_version(
    workflow: Workflow,
    *,
    user: Any = None,
    changelog: str = "",
) -> WorkflowVersion:
    """Create and publish version 1 for ``workflow`` if none exists.

    This is the migration/upgrade entry point: it snapshots the current
    registered definition so existing unversioned executions can be pinned
    rather than silently following future definition changes. Returns the
    existing active version when one already exists.
    """
    existing = active_version(workflow.name)
    if existing is not None:
        return existing
    # Two callers starting at the same time may both observe "no active version".
    # The unique (workflow, version) constraint makes at most one create win; a
    # loser re-reads the winner's row instead of failing, so the upgrade path
    # stays idempotent under concurrency.
    try:
        with transaction.atomic():
            version: WorkflowVersion = _create_version(
                workflow, user=user, changelog=changelog or "Initial version."
            )
    except IntegrityError:
        created = active_version(workflow.name)
        if created is None:
            raise WorkflowVersionError(
                f"Concurrent first-time versioning of '{workflow.name}' left no active version."
            ) from None
        version = created
    _bind_legacy_executions(workflow.name, version)
    return version


def _bind_legacy_executions(workflow_name: str, version: WorkflowVersion) -> None:
    """Pin already-running unversioned executions of ``workflow_name`` to ``version``.

    During an upgrade an installation may have executions started before
    versioning existed (``workflow_version`` NULL). Pinning them guarantees they
    keep the definition they started with instead of silently adopting a newer
    published version later.
    """
    from workflow_kit.models.execution import WorkflowExecution

    WorkflowExecution.objects.filter(
        workflow_name=workflow_name,
        workflow_version__isnull=True,
    ).update(workflow_version=version)


def create_workflow_version(
    workflow: Workflow,
    *,
    from_version: WorkflowVersion | int | None = None,
    user: Any = None,
    changelog: str = "",
) -> WorkflowVersion:
    """Create a new DRAFT version of ``workflow`` (number = max + 1).

    ``from_version`` optionally seeds the new draft from an existing version's
    definition (version cloning); otherwise the live registered definition is
    snapshotted.
    """
    from workflow_kit.models.version import VersionStatus, WorkflowVersion

    latest = WorkflowVersion.objects.filter(workflow=workflow.name).order_by("-version").first()
    number = (latest.version if latest else 0) + 1
    if from_version is not None:
        source = _resolve_version_object(workflow.name, from_version)
        definition = dict(source.definition)
    else:
        definition = serialize_workflow(workflow)
    return WorkflowVersion.objects.create(
        workflow=workflow.name,
        version=number,
        status=VersionStatus.DRAFT,
        definition=definition,
        changelog=changelog,
        created_by=_persistable_user(user),
    )


def update_version(
    version: WorkflowVersion,
    definition: Workflow | dict[str, Any],
    *,
    user: Any = None,
    changelog: str = "",
) -> WorkflowVersion:
    """Replace ``version``'s definition (DRAFT versions only).

    ``definition`` may be a ``Workflow`` object or a JSON snapshot dict. The
    replacement is validated against the engine's configuration rules before
    it is stored.
    """
    if not version.is_draft:
        raise WorkflowVersionError(f"Cannot update version '{version}': only drafts are editable.")
    snapshot = serialize_workflow(definition) if isinstance(definition, Workflow) else definition
    deserialize_workflow(snapshot)  # validate eagerly
    if snapshot.get("name") != version.workflow:
        raise WorkflowVersionError(
            f"Version definition name '{snapshot.get('name')}' does not match "
            f"workflow '{version.workflow}'."
        )
    version.definition = snapshot
    if changelog:
        version.changelog = changelog
    version.save()
    _invalidate_version_cache(version.pk)
    return version


def publish_version(
    version: WorkflowVersion,
    *,
    user: Any = None,
    changelog: str = "",
) -> WorkflowVersion:
    """Validate and publish a DRAFT version.

    Publishing runs the full engine configuration validation on the snapshot
    (states, initial, transitions, conditions, approvals, permissions) and
    rejects invalid definitions, leaving the version in its prior state.
    """
    from django.utils import timezone

    from workflow_kit.models.version import VersionStatus

    if version.status == VersionStatus.PUBLISHED:
        return version
    if version.status == VersionStatus.RETIRED:
        raise WorkflowVersionError(f"Cannot publish retired version '{version}'.")
    get_version_workflow(version)  # raises when the snapshot is invalid
    version.status = VersionStatus.PUBLISHED
    version.published_at = timezone.now()
    if changelog:
        version.changelog = changelog
    version.save()
    _invalidate_version_cache(version.pk)
    return version


def retire_version(
    version: WorkflowVersion,
    *,
    user: Any = None,
    reason: str = "",
) -> WorkflowVersion:
    """Retire a published version so new executions stop selecting it."""
    from django.utils import timezone

    from workflow_kit.models.version import VersionStatus

    if not version.is_published:
        raise WorkflowVersionError(
            f"Cannot retire version '{version}': only published versions may be retired."
        )
    version.status = VersionStatus.RETIRED
    version.retired_at = timezone.now()
    version.save()
    _invalidate_version_cache(version.pk)
    return version


def resolve_start_version(
    workflow: Workflow,
    version: WorkflowVersion | int | None = None,
    *,
    allow_unpublished: bool = False,
) -> WorkflowVersion | None:
    """Resolve which version a new execution of ``workflow`` must bind.

    ``None`` is returned when no versions exist yet — the execution keeps the
    legacy definition-in-Python behaviour (typically right after an upgrade,
    before :func:`ensure_workflow_version` / the data migration ran).

    An explicit ``version`` (int or :class:`WorkflowVersion`) must be published
    unless ``allow_unpublished`` is given for development/testing; retired
    versions are never available for new executions unless explicitly allowed.
    """
    from workflow_kit.models.version import VersionStatus

    if version is None:
        return active_version(workflow.name)
    resolved = _resolve_version_object(workflow.name, version)
    get_version_workflow(resolved)  # ensure the definition is usable
    if resolved.status == VersionStatus.PUBLISHED:
        return resolved
    if allow_unpublished and resolved.status == VersionStatus.DRAFT:
        return resolved
    if resolved.status == VersionStatus.RETIRED and allow_unpublished:
        return resolved
    if resolved.status == VersionStatus.RETIRED:
        raise WorkflowVersionError(
            f"Version '{resolved}' is retired and cannot start new executions."
        )
    raise WorkflowVersionError(
        f"Version '{resolved}' is a draft and cannot start new executions; "
        "publish it or pass allow_unpublished=True explicitly."
    )


def _create_version(
    workflow: Workflow, *, user: Any = None, changelog: str = ""
) -> WorkflowVersion:
    """Create version 1 and publish it (used by :func:`ensure_workflow_version`)."""
    from django.utils import timezone

    from workflow_kit.models.version import VersionStatus, WorkflowVersion

    snapshot = serialize_workflow(workflow)
    return WorkflowVersion.objects.create(
        workflow=workflow.name,
        version=1,
        status=VersionStatus.PUBLISHED,
        definition=snapshot,
        changelog=changelog,
        published_at=timezone.now(),
        created_by=_persistable_user(user),
    )


def _resolve_version_object(workflow_name: str, version: Any) -> WorkflowVersion:
    from workflow_kit.models.version import WorkflowVersion

    if isinstance(version, WorkflowVersion):
        if version.workflow != workflow_name:
            raise WorkflowVersionError(
                f"Version '{version}' belongs to workflow '{version.workflow}', "
                f"not '{workflow_name}'."
            )
        return version
    resolved = WorkflowVersion.objects.filter(workflow=workflow_name, version=version).first()
    if resolved is None:
        raise WorkflowVersionError(f"Workflow '{workflow_name}' has no version '{version}'.")
    return resolved


def _persistable_user(user: Any) -> Any:
    from workflow_kit.audit.service import _persistable_user as audit_user

    return audit_user(user) if user is not None else None
