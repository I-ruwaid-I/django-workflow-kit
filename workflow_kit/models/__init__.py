"""ORM models for Django Workflow Kit.

Phase 1 exposes :class:`WorkflowExecution`, which records a running workflow
instance against an arbitrary Django model. Phase 3 adds the approval and audit
layer: :class:`Approval` (per-step approval requirements) and
:class:`WorkflowEvent` (the append-only audit trail). Phase 9 extends
:class:`Approval` with voting modes, adds :class:`WorkflowDelegation` for
approval delegation and adds :class:`WorkflowVersion` for immutable, numbered
workflow definitions. Executions carry a ``workflow_version`` reference so each
execution stays pinned to the definition it started with. Phase 10 adds
:class:`WorkflowComment` (discussion) and :class:`WorkflowAttachment` (files)
on executions, both surfaced through the timeline as audit events.
"""

from workflow_kit.models.approval import Approval, ApprovalMode, ApprovalStatus
from workflow_kit.models.attachment import WorkflowAttachment
from workflow_kit.models.automation import AutomationRule
from workflow_kit.models.comment import WorkflowComment
from workflow_kit.models.delegation import WorkflowDelegation
from workflow_kit.models.execution import WorkflowExecution
from workflow_kit.models.history import WorkflowEvent, WorkflowEventType
from workflow_kit.models.version import VersionStatus, WorkflowVersion

__all__ = [
    "WorkflowExecution",
    "Approval",
    "ApprovalStatus",
    "ApprovalMode",
    "WorkflowDelegation",
    "WorkflowComment",
    "WorkflowAttachment",
    "WorkflowEvent",
    "WorkflowEventType",
    "WorkflowVersion",
    "VersionStatus",
    "AutomationRule",
]
