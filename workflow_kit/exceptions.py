"""Exception hierarchy for Django Workflow Kit.

All package-specific exceptions derive from :class:`WorkflowError`, so callers
can handle any workflow failure with a single ``except WorkflowError``.
"""

from __future__ import annotations


class WorkflowError(Exception):
    """Base class for all workflow_kit exceptions.

    Every error may carry a structured ``payload`` (a JSON-safe ``dict``) plus
    the ``workflow`` and ``state`` names it relates to and the ``action`` that
    triggered it. The payload gives callers (and the CLI) the same information
    the message renders, without string parsing.
    """

    def __init__(
        self,
        message: str,
        *,
        workflow: str | None = None,
        state: str | None = None,
        action: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.workflow = workflow
        self.state = state
        self.action = action
        self.payload = payload if payload is not None else {}
        super().__init__(message)


class WorkflowConfigurationError(WorkflowError):
    """Raised when a workflow definition is invalid."""


class WorkflowNotFoundError(WorkflowError):
    """Raised when a requested workflow definition cannot be found."""


class InvalidTransitionError(WorkflowError):
    """Raised when a transition is attempted from an invalid source state."""


class PermissionDeniedError(WorkflowError):
    """Raised when the acting user lacks permission for an action."""


class ConditionFailedError(WorkflowError):
    """Raised when a transition condition evaluates to False."""


class ConditionEvaluationError(WorkflowError):
    """Raised when a condition cannot be evaluated (e.g. a missing field)."""


class WorkflowAlreadyCompletedError(WorkflowError):
    """Raised when an action is attempted on a completed workflow."""


class WorkflowConflictError(WorkflowError):
    """Raised when a concurrent action conflicts with the current state."""


class ApprovalError(WorkflowError):
    """Base class for approval-engine errors."""


class ApprovalNotPendingError(ApprovalError):
    """Raised when no pending approval exists for the current step."""


class AuditError(WorkflowError):
    """Raised when an operation would break the audit trail invariants."""


class AttachmentError(WorkflowError):
    """Raised when an attachment upload violates package security policy.

    Covers disallowed file types, files over the configured size limit and
    unsafe (path-traversal) file names.
    """


class WorkflowVersionError(WorkflowError):
    """Base class for workflow-versioning errors.

    Covers invalid, non-serializable, already-published or otherwise unusable
    workflow versions.
    """


class WorkflowValidationError(WorkflowError):
    """Raised when a workflow definition fails structural validation.

    The ``payload["issues"]`` entry is a list of
    :class:`~workflow_kit.engine.validation.ValidationIssue` dicts describing
    every problem found, so callers and the CLI can render a report without
    parsing the message.
    """


class SimulationError(WorkflowError):
    """Base class for errors raised by the dry-run simulation engine."""


class NoPathFoundError(SimulationError):
    """Raised when a simulation cannot reach a terminal state within its step budget."""
