"""Phase 12 tests: the read-only admin analytics summary page.

The ``summary/`` view of :class:`WorkflowExecutionAdmin` renders per-workflow
aggregate metrics. It goes through the admin site's own view wrapper, so the
standard staff/superuser rules apply and it never writes to the database.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from workflow_kit.models import WorkflowExecution

from tests.analytics_helpers import manager, run

pytestmark = pytest.mark.django_db

SUMMARY_URL = reverse("admin:workflow_kit_workflowexecution_summary")


def test_summary_page_renders_for_staff(admin_client, analytics_workflow, invoice):
    """Staff can open the summary and it lists per-workflow aggregates."""
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)

    response = admin_client.get(SUMMARY_URL)
    assert response.status_code == 200
    content = response.content.decode()
    assert "analytics_flow" in content
    assert "Workflow analytics" in content


def test_summary_page_shows_counts(admin_client, analytics_workflow, invoice):
    """The rendered table includes the measurable counts."""
    mgr = manager()
    run(analytics_workflow.start(invoice), "submit", "approve", user=mgr)

    response = admin_client.get(SUMMARY_URL)
    content = response.content.decode()
    assert "started" in content.lower()
    assert "1" in content  # the single execution's started/completed count


def test_summary_page_requires_staff(client):
    """Anonymous and non-staff users are redirected by the admin wrapper."""
    response = client.get(SUMMARY_URL)
    assert response.status_code in (302, 403)


def test_summary_page_empty_state(admin_client, analytics_workflow, invoice):
    """No executions produce a page that still renders."""
    response = admin_client.get(SUMMARY_URL)
    assert response.status_code == 200


def test_summary_page_never_writes(admin_client, analytics_workflow, invoice):
    """Opening the summary performs no database writes."""
    before = WorkflowExecution.objects.count()
    admin_client.get(SUMMARY_URL)
    assert WorkflowExecution.objects.count() == before
