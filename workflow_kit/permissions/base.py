"""Extensible authorization interfaces for Django Workflow Kit.

Applications implement :class:`PermissionProvider` to express custom
authorization logic without modifying the workflow engine. Built-in checks
(Django groups and Django permissions) are handled by
:mod:`workflow_kit.permissions.evaluate`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PermissionProvider(ABC):
    """Interface for custom authorization logic.

    Subclass and implement :meth:`can_execute` to decide whether ``user`` may
    perform the transition described by ``context``.
    """

    @abstractmethod
    def can_execute(self, context: Any) -> bool:
        """Return True when the action described by ``context`` is allowed."""
        raise NotImplementedError
