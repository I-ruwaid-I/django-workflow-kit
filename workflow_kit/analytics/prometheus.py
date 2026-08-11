"""Dependency-free Prometheus text exposition for workflow analytics (Phase 12).

Renders the analytics aggregates as Prometheus text format (OpenMetrics-style
counters and summaries) without requiring the ``prometheus_client`` package —
the core package stays lightweight. Labels use only low-cardinality values
(workflow name, status), never arbitrary execution ids.

Integrations that already speak ``prometheus_client`` can consume the same
Python analytics API directly; this module is an optional, dependency-free
bridge.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from workflow_kit.analytics.approvals import approval_metrics
from workflow_kit.analytics.duration import completion_metrics
from workflow_kit.analytics.metrics import execution_metrics
from workflow_kit.analytics.sla import sla_metrics


def _label(label: str) -> str:
    """Escape a Prometheus label value so it is always valid."""
    return label.replace("\\", "\\\\").replace('"', '\\"')


def prometheus_metrics_text(
    *,
    workflow: str | None = None,
    workflow_version: int | str | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    state: str | None = None,
) -> str:
    """Render execution, approval and SLA analytics as Prometheus text format.

    Returns a complete, well-formed exposition (a series of ``# HELP`` /
    ``# TYPE`` header lines followed by sample lines) suitable for scraping.
    """
    metrics = execution_metrics(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
        state=state,
    )
    completion = completion_metrics(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
        state=state,
    )
    approvals = approval_metrics(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
        state=state,
    )
    sla = sla_metrics(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
        state=state,
    )
    labels = _label(workflow) if workflow else ""

    lines: list[str] = []
    execution_samples = [
        ("workflow_executions_started_total", "counter", metrics.started),
        ("workflow_executions_active", "gauge", metrics.active),
        ("workflow_executions_completed_total", "counter", metrics.completed),
        ("workflow_executions_rejected_total", "counter", metrics.rejected),
        ("workflow_executions_failed_total", "counter", metrics.failed),
        ("workflow_executions_cancelled_total", "counter", metrics.cancelled),
        ("workflow_executions_escalated_total", "counter", metrics.escalated),
        ("workflow_executions_sla_breached_total", "counter", metrics.sla_breached),
    ]
    for name, kind, value in execution_samples:
        lines.append(f"# HELP {name} {kind} workflow execution count.")
        lines.append(f"# TYPE {name} {kind}")
        lines.append(f'{name}{{workflow="{labels}"}} {value}')

    if completion.completed:
        summary = "workflow_execution_completion_duration_seconds"
        lines.append(f"# TYPE {summary} summary")
        lines.append(f'{summary}_count{{workflow="{labels}"}} {completion.completed}')
        lines.append(
            f'{summary}_sum{{workflow="{labels}"}} '
            f"{completion.completed * (completion.duration.average or 0.0)}"
        )
        if completion.duration.maximum is not None:
            lines.append(
                f'{summary}_bucket{{workflow="{labels}",le="+Inf"}} {completion.completed}'
            )

    approval_samples = [
        ("workflow_approval_requests_total", approvals.requested),
        ("workflow_approval_approved_total", approvals.approved),
        ("workflow_approval_rejected_total", approvals.rejected),
        ("workflow_approval_pending", approvals.pending),
        ("workflow_approval_cancelled_total", approvals.cancelled),
        ("workflow_approval_escalated_total", approvals.escalated),
        ("workflow_approval_sla_breached_total", approvals.sla_breached),
    ]
    for name, value in approval_samples:
        lines.append(f"# TYPE {name} counter")
        lines.append(f'{name}{{workflow="{labels}"}} {value}')

    lines.append("# TYPE workflow_sla_compliance_ratio gauge")
    lines.append(
        f'workflow_sla_compliance_ratio{{workflow="{labels}"}} '
        f"{sla.compliance_rate if sla.compliance_rate is not None else 0.0}"
    )
    lines.append("# TYPE workflow_sla_breaches_total counter")
    lines.append(f'workflow_sla_breaches_total{{workflow="{labels}"}} {sla.breached}')
    return "\n".join(lines) + "\n" if lines else ""


def collect_metrics(
    *,
    workflow: str | None = None,
    workflow_version: int | str | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    """Return the analytics aggregates behind the exposition as a plain dict.

    A convenience for consumers that want the raw numbers rather than the
    rendered text (e.g. a custom dashboard or a ``prometheus_client`` writer).
    """
    metrics = execution_metrics(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
        state=state,
    )
    completion = completion_metrics(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
        state=state,
    )
    approvals = approval_metrics(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
        state=state,
    )
    sla = sla_metrics(
        workflow=workflow,
        workflow_version=workflow_version,
        start=start,
        end=end,
        state=state,
    )
    return {
        "execution": metrics.to_dict(),
        "completion": completion.to_dict(),
        "approvals": approvals.to_dict(),
        "sla": sla.to_dict(),
    }
