"""Approval requirement abstraction (Phase 9).

A workflow state's *approval requirement* declares how the approvals that
guard that state must be satisfied before the execution advances:

- :data:`ApprovalMode.ALL` — every approver assigned to the state must approve
  (parallel, "all-of");
- :data:`ApprovalMode.ANY` — the first decision (approve *or* reject) settles
  the step ("any-of");
- :data:`ApprovalMode.QUORUM` — at least ``quorum`` approvals are required to
  advance; a single rejection still rejects the step.

Approvers are resolved at approval-creation time to concrete assignments so
that only persisted facts (group names / usernames) are stored. They may be
declared statically (group names, usernames, user instances) or dynamically
through a :class:`ApproverResolver` or plain callable that returns any of the
previous.

Authorization is always delegated to the Phase 2 permission system; the
assignment declared here only decides *which* pending approval a user may
fill, on top of the transition's own permission requirement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.db.models import Model

from workflow_kit.exceptions import WorkflowConfigurationError

if TYPE_CHECKING:
    from workflow_kit.engine.workflow import Workflow
    from workflow_kit.models.execution import WorkflowExecution


class ApprovalMode(str):
    """Supported approval modes for a single step."""

    ALL = "ALL"
    ANY = "ANY"
    QUORUM = "QUORUM"


@dataclass(frozen=True)
class ApprovalContext:
    """Controlled context handed to dynamic approver resolvers.

    Only the workflow/execution pair, the step and the business object are
    exposed; resolvers never receive unrestricted state.
    """

    workflow: Workflow
    execution: WorkflowExecution
    step: str
    object: Any = None

    @classmethod
    def build(
        cls,
        workflow: Workflow,
        execution: WorkflowExecution,
        step: str,
    ) -> ApprovalContext:
        """Build a context for ``step`` of ``execution``."""
        return cls(
            workflow=workflow,
            execution=execution,
            step=step,
            object=getattr(execution, "object", None),
        )


class ApproverResolver(ABC):
    """Interface for dynamic approver resolution.

    Subclass and implement :meth:`resolve` to turn an :class:`ApprovalContext`
    into the users or group names that may fill a step's approvals.
    """

    @abstractmethod
    def resolve(self, context: ApprovalContext) -> Any:
        """Return the approver(s) for ``context``.

        May return ``None`` (no slot), a single group name / username / user
        instance, or a list of those.
        """
        raise NotImplementedError


def _assignment_for(value: Any) -> dict[str, Any]:
    """Materialize one static approver value into a persisted assignment."""
    if isinstance(value, str):
        if "." in value:
            return {"type": "user", "username": value}
        return {"type": "group", "name": value}
    if isinstance(value, Model) and getattr(value, "is_authenticated", False):
        username = getattr(value, "username", None)
        return {"type": "user", "username": str(username) if username else str(value.pk)}
    raise WorkflowConfigurationError(f"Cannot resolve approver {value!r}.")


@dataclass(frozen=True)
class ApprovalRequirement:
    """The approval rule attached to one workflow state.

    ``mode`` chooses the :class:`ApprovalMode`. ``approvers`` lists the
    declared approvers (group names, usernames, user instances,
    :class:`ApproverResolver` objects or callables). An empty ``approvers``
    list keeps the Phase 3 behaviour: a single approval that any authorized
    user may fill.

    ``quorum`` only applies to :data:`ApprovalMode.QUORUM`; ``allow_self``
    controls whether the user who initiated the execution may decide this
    step; ``sla`` optionally sets a per-step deadline used for the
    escalation/SLA helpers.
    """

    mode: str = ApprovalMode.ALL
    approvers: Sequence[Any] = field(default_factory=tuple)
    quorum: int = 1
    allow_self: bool = True
    sla: timedelta | None = None
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in (ApprovalMode.ALL, ApprovalMode.ANY, ApprovalMode.QUORUM):
            raise WorkflowConfigurationError(f"Invalid approval mode: {self.mode!r}.")
        if self.mode == ApprovalMode.QUORUM and self.quorum < 1:
            raise WorkflowConfigurationError(
                f"A QUORUM approval requirement needs quorum >= 1, got {self.quorum}."
            )


def resolve_approvers(
    requirement: ApprovalRequirement,
    context: ApprovalContext,
) -> list[dict[str, Any]]:
    """Materialize ``requirement.approvers`` into persisted assignments.

    Returns one assignment dict per approver slot, in declaration order. An
    empty ``approvers`` list yields a single unassigned
    ``{"type": "any"}`` assignment so the Phase 3 intact behaviour
    is preserved.
    """
    if not requirement.approvers:
        return [{"type": "any"}]

    assignments: list[dict[str, Any]] = []
    for approver in requirement.approvers:
        if isinstance(approver, ApproverResolver):
            resolved = approver.resolve(context)
        elif callable(approver):
            resolved = approver(context)
        else:
            resolved = approver
        if resolved is None:
            continue
        values = resolved if isinstance(resolved, (list, tuple)) else [resolved]
        for value in values:
            assignments.append(_assignment_for(value))
    return assignments
