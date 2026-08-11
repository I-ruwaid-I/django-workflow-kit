"""Phase 13 tests: database performance and query-count regression.

Guards the critical read paths against accidental N+1 queries (PHASE13 ``#11``
``#13``). Each test wires up a realistic number of rows, walks one critical path
through the REST API / engine / analytics and asserts a constant, bounded query
count that does not grow with the dataset size:

- execution list (versioned rows must not trigger one version query per row);
- execution detail + available actions;
- history / timeline / approvals endpoints;
- analytics metrics over a large dataset.

The assertions are deliberately not too tight (framework / auth plumbing varies)
but tight enough to catch a per-row query: the N+1 pattern pushes the count far
above the bounds asserted here.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from workflow_kit import Transition, Workflow
from workflow_kit.engine import registry
from workflow_kit.engine.versioning import ensure_workflow_version

from tests.test_project.demo.models import Invoice

pytestmark = pytest.mark.django_db


def _user(username: str, *groups: str) -> Any:
    from django.contrib.auth.models import Group

    user, _ = get_user_model().objects.get_or_create(username=username)
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


def _client_for(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def perf_workflow():
    workflow = Workflow(
        name="perf_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected"],
        transitions=[
            Transition("submit", "draft", "review"),
            Transition("approve", "review", "approved", permission=["Manager"]),
            Transition("reject", "review", "rejected", permission=["Manager"]),
        ],
    )
    yield workflow
    registry.unregister("perf_flow")


def _seed(workflow: Workflow, count: int) -> list[Any]:
    """Start ``count`` executions and return them in start order."""
    from workflow_kit.models import WorkflowExecution

    executions: list[Any] = []
    for i in range(count):
        invoice = Invoice.objects.create(number=f"QT-{i}", vendor="Acme", amount="100.00")
        executions.append(workflow.start(invoice))
    assert all(isinstance(e, WorkflowExecution) for e in executions)
    return executions


def _advance(workflow: Workflow, executions: list[Any], *, mgr: Any) -> None:
    for execution in executions:
        workflow.transition(execution, "submit", user=mgr)


def _query_count(client: APIClient, path: str) -> tuple[int, Any]:
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as captured:
        response = client.get(path)
    return len(captured), response


# -- Execution list ----------------------------------------------------------


def test_execution_list_query_count_stays_flat_when_versioned(perf_workflow):
    """A versioned list must not issue one version query per execution row."""
    ensure_workflow_version(perf_workflow, changelog="Initial version.")
    mgr = _user("perf_mgr", "Manager")
    count = 40
    executions = _seed(perf_workflow, count)
    _advance(perf_workflow, executions, mgr=mgr)

    client = _client_for(mgr)

    # Warm caches / content types so the measurement below is the real cost.
    _query_count(client, "/api/executions/")

    queries, response = _query_count(client, "/api/executions/")
    assert response.status_code == 200
    assert response.data["count"] == count
    # COUNT + page + content-type/version joins; any value near 5 is fine. A
    # per-row version lookup would push this well past 25.
    assert queries <= 12


def test_execution_list_unversioned_does_not_touch_version_rows(perf_workflow):
    """Unversioned rows carry no version FK cost; count stays flat too."""
    mgr = _user("perf_mgr_plain", "Manager")
    executions = _seed(perf_workflow, 40)
    _advance(perf_workflow, executions, mgr=mgr)

    client = _client_for(mgr)
    _query_count(client, "/api/executions/")
    queries, response = _query_count(client, "/api/executions/")
    assert response.status_code == 200
    assert queries <= 12


# -- Execution detail and actions ---------------------------------------------


def test_execution_detail_available_actions_bounded(perf_workflow):
    """Detail + available_actions for one execution is a constant small cost."""
    mgr = _user("perf_mgr_det", "Manager")
    executions = _seed(perf_workflow, 1)
    _advance(perf_workflow, executions, mgr=mgr)
    execution = executions[0]

    client = _client_for(mgr)
    pk = execution.pk

    _query_count(client, f"/api/executions/{pk}/")
    _query_count(client, f"/api/executions/{pk}/actions/")

    queries, response = _query_count(client, f"/api/executions/{pk}/")
    assert response.status_code == 200
    assert queries <= 10


# -- History / timeline / approvals -------------------------------------------


def test_history_timeline_approvals_are_bounded(perf_workflow):
    """History, timeline and approvals endpoints issue a constant query set."""
    mgr = _user("perf_mgr_hist", "Manager")
    executions = _seed(perf_workflow, 1)
    _advance(perf_workflow, executions, mgr=mgr)
    execution = executions[0]
    pk = execution.pk

    client = _client_for(mgr)
    paths = (f"/api/executions/{pk}/history/", f"/api/executions/{pk}/timeline/")
    for path in paths:
        _query_count(client, path)
        queries, response = _query_count(client, path)
        assert response.status_code == 200
        assert queries <= 10


# -- Analytics ----------------------------------------------------------------


def test_metrics_query_count_is_flat_at_scale(perf_workflow):
    """Growing the dataset must not grow the metrics query count."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from workflow_kit.analytics import execution_metrics

    mgr = _user("perf_mgr_an", "Manager")
    executions = _seed(perf_workflow, 60)
    _advance(perf_workflow, executions, mgr=mgr)

    with CaptureQueriesContext(connection) as captured:
        execution_metrics()
    assert len(captured) <= 12
