"""Approval engine built on top of the workflow engine.

Phase 3 provides sequential approvals at the engine level: each non-terminal
step an execution reaches gets pending :class:`~workflow_kit.models.Approval`
records, and resolving them executes the corresponding transition through the
existing engine. Authorization is always delegated to the Phase 2 permission
system.

Phase 9 adds step requirements (:class:`ApprovalRequirement`), parallel voting
modes, delegation, escalation and SLA tracking. The decision API remains
:func:`approve_execution` / :func:`reject_execution`, which now decide a single
approval and resolve the step once its requirement is satisfied.

Only the requirement definitions (``requirements`` submodule) are imported
eagerly; the service layer stays lazy so importing ``workflow_kit`` never pulls
in ORM models before Django is configured.
"""

from typing import Any

from workflow_kit.approvals.requirements import (
    ApprovalContext,
    ApprovalMode,
    ApprovalRequirement,
    ApproverResolver,
    resolve_approvers,
)

_SERVICE_NAMES = frozenset(
    {
        "approve_execution",
        "reject_execution",
        "pending_approvals",
        "step_approvals",
        "overdue_approvals",
        "delegate_approval",
        "revoke_delegation",
        "escalate_execution",
    }
)


def __getattr__(name: str) -> Any:
    """Lazily load the approval service so models are not imported early."""
    if name in _SERVICE_NAMES:
        from workflow_kit.approvals import service as service_module

        return getattr(service_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(list(globals())) | set(_SERVICE_NAMES) | {*_PUBLIC_NAMES})


_PUBLIC_NAMES = frozenset(
    {
        "ApprovalContext",
        "ApprovalMode",
        "ApprovalRequirement",
        "ApproverResolver",
        "resolve_approvers",
    }
)


__all__ = [
    "approve_execution",
    "reject_execution",
    "pending_approvals",
    "step_approvals",
    "overdue_approvals",
    "delegate_approval",
    "revoke_delegation",
    "escalate_execution",
    "ApprovalMode",
    "ApprovalRequirement",
    "ApprovalContext",
    "ApproverResolver",
    "resolve_approvers",
]
