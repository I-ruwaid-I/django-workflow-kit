"""Authorization evaluation for workflow transitions.

A :class:`~workflow_kit.engine.workflow.Transition` may declare a
``permission`` requirement. The requirement can be:

- ``None`` — no authorization is required (any caller may transition).
- A string ``"app_label.codename"`` — a Django permission, checked via
  ``user.has_perm``.
- A string without a dot — a Django group name, checked against the user's
  current group membership.
- A list/tuple of the above — **all** requirements must pass (AND).
- A :class:`~workflow_kit.permissions.base.PermissionProvider` instance or a
  plain callable accepting a :class:`PermissionContext`.

Documented policy decisions (tested in ``tests/test_permissions.py``):

- Anonymous or missing users are denied for protected transitions.
- Django superusers bypass workflow authorization checks.
- Group membership is resolved at execution time; it is never cached inside a
  workflow execution.
"""

from __future__ import annotations

from typing import Any

from workflow_kit.exceptions import WorkflowConfigurationError
from workflow_kit.permissions.base import PermissionProvider
from workflow_kit.permissions.context import PermissionContext


def is_authenticated(user: Any) -> bool:
    """Return whether ``user`` is an authenticated user (None and anonymous are False)."""
    if user is None:
        return False
    return bool(getattr(user, "is_authenticated", False))


def is_superuser(user: Any) -> bool:
    """Return whether ``user`` is a Django superuser."""
    if user is None:
        return False
    return bool(getattr(user, "is_superuser", False))


def is_authorized(
    user: Any,
    workflow: Any,
    execution: Any,
    transition: Any,
) -> bool:
    """Return whether ``user`` may execute ``transition`` for ``execution``."""
    spec = transition.permission
    if spec is None:
        return True
    if not is_authenticated(user):
        return False
    if is_superuser(user):
        return True

    group_names: frozenset[str] | None = None
    groups = getattr(user, "groups", None)
    if groups is not None:
        group_names = frozenset(groups.values_list("name", flat=True))

    context = PermissionContext(
        user=user,
        workflow=workflow,
        execution=execution,
        transition=transition,
        object=getattr(execution, "object", None),
    )

    requirements = spec if isinstance(spec, (list, tuple)) else (spec,)
    for requirement in requirements:
        if isinstance(requirement, PermissionProvider):
            if not requirement.can_execute(context):
                return False
        elif isinstance(requirement, str):
            if "." in requirement:
                if not user.has_perm(requirement):
                    return False
            elif group_names is None or requirement not in group_names:
                return False
        elif callable(requirement):
            if not requirement(context):
                return False
        else:
            raise WorkflowConfigurationError(f"Invalid permission requirement: {requirement!r}")
    return True
