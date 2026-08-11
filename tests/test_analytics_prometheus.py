"""Phase 12 tests: dependency-free Prometheus exposition.

``prometheus_metrics_text`` renders the analytics aggregates in Prometheus
text format; ``collect_metrics`` returns the same numbers as a plain dict.
These assertions only validate the rendering and the numbers, never that
``prometheus_client`` is installed (it deliberately is not required).
"""

from __future__ import annotations

import pytest
from workflow_kit.analytics import (
    collect_metrics,
    prometheus_metrics_text,
)

from tests.analytics_helpers import manager, run

pytestmark = pytest.mark.django_db


def test_prometheus_text_exposes_samples(analytics_workflow, invoice):
    """Every expected metric family appears with a HELP and TYPE line."""
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)

    text = prometheus_metrics_text(workflow="analytics_flow")
    assert text.startswith("# HELP")
    assert "# TYPE workflow_executions_started_total counter" in text
    assert "# TYPE workflow_executions_active gauge" in text
    assert 'workflow_executions_started_total{workflow="analytics_flow"} 1' in text
    assert 'workflow_executions_completed_total{workflow="analytics_flow"} 1' in text
    assert "# TYPE workflow_approval_requests_total counter" in text
    assert "# TYPE workflow_sla_compliance_ratio gauge" in text
    assert text.endswith("\n")


def test_prometheus_text_includes_completion_summary(analytics_workflow, invoice):
    """Completed executions add a summary family with count/sum/+Inf bucket."""
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)

    text = prometheus_metrics_text(workflow="analytics_flow")
    assert "# TYPE workflow_execution_completion_duration_seconds summary" in text
    assert (
        'workflow_execution_completion_duration_seconds_count{workflow="analytics_flow"} 1' in text
    )
    assert 'le="+Inf"' in text


def test_prometheus_text_escapes_labels(analytics_workflow, invoice):
    """Quotes and backslashes in workflow names are escaped for the exposition."""
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)

    text = prometheus_metrics_text(workflow='a"\\b')
    assert 'workflow="a\\"\\\\b"' in text


def test_prometheus_text_empty_set(analytics_workflow):
    """Empty scopes still emit well-formed sample lines with zero counts."""
    text = prometheus_metrics_text(workflow="analytics_flow")
    assert 'workflow_executions_started_total{workflow="analytics_flow"} 0' in text


def test_collect_metrics_shape(analytics_workflow, invoice):
    """``collect_metrics`` mirrors the exposition's underlying aggregates."""
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)

    data = collect_metrics(workflow="analytics_flow")
    assert set(data) == {"execution", "completion", "approvals", "sla"}
    assert data["execution"]["started"] == 1
    assert data["execution"]["completed"] == 1
    assert data["approvals"]["approved"] == 1
    assert data["sla"]["tracked"] == 0
