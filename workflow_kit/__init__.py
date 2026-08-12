"""Django Workflow Kit.

A modern, extensible workflow and approval engine for Django applications.

Phase 1 exposes the core workflow engine: ``Workflow``, ``State`` and
``Transition`` definitions plus ``WorkflowExecution`` (ORM-backed) and
``get_workflow`` for resolving definitions by name. Phase 2 adds
authorization: ``PermissionProvider``, ``PermissionContext`` and the
``PermissionDeniedError`` raised when an action is not allowed. Phase 3 adds
sequential approvals, the append-only audit trail and the derived timeline.
Phase 4 adds the condition system (``Condition``, ``ConditionContext`` and the
built-in conditions) that powers conditional routing. Phase 5 adds domain
events (``DomainEvent``, ``EventType`` and ``subscribe``/``dispatch``) plus a
notification layer built on top of those events. Phase 6 adds an optional DRF
REST API under ``workflow_kit.api`` that exposes executions, actions,
transitions, history, timeline and approvals as a thin HTTP layer over the
existing engine. Phase 9 adds workflow versioning: immutable, numbered
:class:`WorkflowVersion` definitions (``DRAFT`` / ``PUBLISHED`` / ``RETIRED``)
and version-bound executions — every execution starts pinned to the definition
version it was created with and never silently switches. Phase 10 adds
collaboration on executions: comments (``execution.add_comment``) and
attachments (:class:`WorkflowAttachment`, stored through Django's default
storage), both recorded in the timeline as audit events and emitted as domain
events. Phase 11 adds the developer experience: a declarative definition
parser (``parse_workflow_def``), static validation with structured reports
(``validate_definition`` / ``ValidationReport``), introspection and path
enumeration (``workflow_to_dict``, ``reachable_states``), a dry-run simulation
engine (``simulate`` / ``simulate_all``), action diagnostics (``explain`` /
``why_not``), graph rendering (``to_dot`` / ``to_mermaid``), the
``python -m workflow_kit.cli`` command line interface, testing utilities under
``workflow_kit.testing`` and structured exceptions carrying JSON-safe
payloads. Phase 12 adds observability and analytics: ``execution_metrics`` /
``version_analytics`` (what is happening), ``completion_metrics`` /
``state_durations`` / ``bottlenecks`` (how long it takes), ``approval_metrics``
/ ``approval_totals`` (where approvals slow things down), ``sla_metrics`` /
``escalation_analytics`` (how often SLAs are breached), an optional
dependency-free Prometheus exposition (``prometheus_metrics_text``), structured
event logging with correlation ids (``workflow_kit.observability``), read-only
REST analytics endpoints and an admin analytics summary.
"""

from __future__ import annotations

from workflow_kit.analytics import (
    AnalyticsError,
    ApprovalMetrics,
    CompletionMetrics,
    DurationStats,
    ExecutionMetrics,
    SlaMetrics,
    StateDuration,
    VersionAnalytics,
    approval_metrics,
    approval_totals,
    bottlenecks,
    collect_metrics,
    completion_metrics,
    escalation_analytics,
    execution_metrics,
    prometheus_metrics_text,
    sla_metrics,
    state_durations,
    version_analytics,
)
from workflow_kit.approvals.requirements import (
    ApprovalContext,
    ApprovalMode,
    ApprovalRequirement,
    ApproverResolver,
)
from workflow_kit.conditions import (
    All,
    Any,
    Condition,
    ConditionContext,
    FieldEquals,
    FieldNotEquals,
    GreaterThan,
    GreaterThanOrEqual,
    IsFalse,
    IsTrue,
    LessThan,
    LessThanOrEqual,
    Not,
    build_condition_context,
    conditions_met,
)
from workflow_kit.engine.explain import explain, why_not
from workflow_kit.engine.introspection import reachable_states, workflow_to_dict
from workflow_kit.engine.parse import parse_workflow_def
from workflow_kit.engine.registry import all_workflows, get_workflow
from workflow_kit.engine.simulation import simulate, simulate_all
from workflow_kit.engine.validation import ValidationIssue, ValidationReport, validate_definition
from workflow_kit.engine.workflow import State, Transition, Workflow
from workflow_kit.events import (
    DomainEvent,
    EventType,
    ObjectRef,
    default_dispatcher,
    subscribe,
)
from workflow_kit.exceptions import (
    ApprovalError,
    ApprovalNotPendingError,
    AttachmentError,
    AuditError,
    ConditionEvaluationError,
    ConditionFailedError,
    InvalidTransitionError,
    NoPathFoundError,
    PermissionDeniedError,
    SimulationError,
    WorkflowAlreadyCompletedError,
    WorkflowConfigurationError,
    WorkflowError,
    WorkflowNotFoundError,
    WorkflowValidationError,
    WorkflowVersionError,
)
from workflow_kit.graph import render as render_graph
from workflow_kit.graph import to_dot, to_mermaid
from workflow_kit.observability import (
    StructuredEventLogger,
    correlation_id,
    current_correlation_id,
    install_structured_logging,
    reset_correlation_id,
    set_correlation_id,
    uninstall_structured_logging,
)
from workflow_kit.permissions import PermissionContext, PermissionProvider
from workflow_kit.timeline.event import TimelineEvent

__version__ = "1.0.0"

__all__ = [
    "State",
    "Transition",
    "Workflow",
    "get_workflow",
    "all_workflows",
    "WorkflowError",
    "WorkflowConfigurationError",
    "WorkflowVersionError",
    "InvalidTransitionError",
    "PermissionDeniedError",
    "WorkflowAlreadyCompletedError",
    "WorkflowNotFoundError",
    "PermissionProvider",
    "PermissionContext",
    "ApprovalError",
    "ApprovalNotPendingError",
    "AttachmentError",
    "AuditError",
    "ConditionFailedError",
    "ConditionEvaluationError",
    "Condition",
    "ConditionContext",
    "build_condition_context",
    "conditions_met",
    "FieldEquals",
    "FieldNotEquals",
    "GreaterThan",
    "GreaterThanOrEqual",
    "LessThan",
    "LessThanOrEqual",
    "IsTrue",
    "IsFalse",
    "All",
    "Any",
    "Not",
    "EventType",
    "DomainEvent",
    "ObjectRef",
    "subscribe",
    "default_dispatcher",
    "TimelineEvent",
    "ApprovalMode",
    "ApprovalRequirement",
    "ApprovalContext",
    "ApproverResolver",
    "parse_workflow_def",
    "validate_definition",
    "ValidationReport",
    "ValidationIssue",
    "workflow_to_dict",
    "reachable_states",
    "simulate",
    "simulate_all",
    "explain",
    "why_not",
    "to_dot",
    "to_mermaid",
    "render_graph",
    "SimulationError",
    "NoPathFoundError",
    "WorkflowValidationError",
    "AnalyticsError",
    "DurationStats",
    "ExecutionMetrics",
    "VersionAnalytics",
    "CompletionMetrics",
    "StateDuration",
    "ApprovalMetrics",
    "SlaMetrics",
    "execution_metrics",
    "version_analytics",
    "completion_metrics",
    "state_durations",
    "bottlenecks",
    "approval_metrics",
    "approval_totals",
    "sla_metrics",
    "escalation_analytics",
    "prometheus_metrics_text",
    "collect_metrics",
    "install_structured_logging",
    "uninstall_structured_logging",
    "StructuredEventLogger",
    "correlation_id",
    "current_correlation_id",
    "set_correlation_id",
    "reset_correlation_id",
    "__version__",
]
