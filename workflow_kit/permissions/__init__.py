"""Permissions and authorization for Django Workflow Kit.

Phase 2 adds a generic authorization layer on top of the Phase 1 engine:
Django users, groups, Django permissions, and custom
:class:`PermissionProvider` instances are all supported by the engine's
transition path.
"""

from workflow_kit.permissions.base import PermissionProvider
from workflow_kit.permissions.context import PermissionContext
from workflow_kit.permissions.evaluate import is_authorized

__all__ = ["PermissionProvider", "PermissionContext", "is_authorized"]
