"""Analytics and observability backends (Phase 12).

The analytics layer turns the data already produced by the workflow engine —
executions, approvals, the append-only audit trail, events and versions — into
operational information. It answers:

* what is happening (:func:`execution_metrics`, :func:`version_analytics`);
* how long it is taking (:func:`completion_metrics`, :func:`state_durations`,
  :func:`bottlenecks`);
* where approvals slow things down (:func:`approval_metrics`,
  :func:`approval_totals`);
* how often SLAs are breached (:func:`sla_metrics`,
  :func:`escalation_analytics`).

Everything is read-only and derived from existing tables — no second data or
history system is written. Counts use database aggregations; only the small
columns required for duration statistics are pulled into Python.

An optional, dependency-free Prometheus text exposition is provided by
:func:`prometheus_metrics_text`, keeping analytics bridgeable to monitoring
infrastructure without coupling the core package to a metrics client.
"""

from __future__ import annotations

from workflow_kit.analytics.approvals import ApprovalMetrics, approval_metrics, approval_totals
from workflow_kit.analytics.base import AnalyticsError, DurationStats
from workflow_kit.analytics.duration import (
    CompletionMetrics,
    StateDuration,
    bottlenecks,
    completion_metrics,
    state_durations,
)
from workflow_kit.analytics.metrics import (
    ExecutionMetrics,
    VersionAnalytics,
    execution_metrics,
    version_analytics,
)
from workflow_kit.analytics.prometheus import collect_metrics, prometheus_metrics_text
from workflow_kit.analytics.sla import SlaMetrics, escalation_analytics, sla_metrics

__all__ = [
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
]
