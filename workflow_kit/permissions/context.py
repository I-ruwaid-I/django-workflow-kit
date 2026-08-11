"""The controlled authorization context passed to permission providers.

Providers never see unrestricted globals or raw request objects; they receive
exactly the fields defined here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PermissionContext:
    """Controlled context handed to a :class:`PermissionProvider`.

    ``object`` is a convenience alias for ``execution.object`` — the business
    object the workflow is running against.
    """

    user: Any
    workflow: Any
    execution: Any
    transition: Any
    object: Any = None
