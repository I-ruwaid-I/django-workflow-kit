"""Demo smoke test.

Runs against the REAL demo database (examples/invoice_approval/db.sqlite3) so
the created invoices are visible in the running demo. This is a manual smoke
test, not part of pytest (which uses a throwaway DB).

Run from the repository root:
    .venv/Scripts/python.exe scripts/demo_smoke.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples" / "invoice_approval"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.utils import timezone  # noqa: E402
from invoices.models import Invoice  # noqa: E402
from invoices.services import (  # noqa: E402
    approve_invoice,
    create_invoice,
    invoice_execution_version,
    publish_invoice_v2,
    submit_invoice,
)
from invoices.workflow import invoice_workflow  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from workflow_kit.exceptions import WorkflowNotFoundError  # noqa: E402

# The demo DB is persistent, so give every run-tagged invoice a fresh number.
_RUN = timezone.now().strftime("%m%d%H%M%S")


def _invoice(number: str) -> Invoice:
    invoice, _ = Invoice.objects.get_or_create(
        number=f"SMOKE-{_RUN}-{number}",
        defaults={"customer_name": "Acme Corp", "amount": "7500.00"},
    )
    try:
        _ = invoice.execution
    except WorkflowNotFoundError:
        invoice_workflow.start(invoice)
    return invoice


def main() -> None:
    call_command("seed_demo_users", verbosity=0)
    users = {u.username: u for u in User.objects.all()}

    emp = users["employee"]
    mgr = users["manager"]
    fin = users["finance"]

    inv1 = _invoice("21")
    submit_invoice(inv1, user=emp)
    print(f"1  submitted {inv1.number}: {inv1.current_state}")

    inv2 = _invoice("22")
    submit_invoice(inv2, user=emp)
    approve_invoice(inv2, mgr)
    print(f"2  manager-approved {inv2.number}: {inv2.current_state}")

    inv3 = _invoice("23")
    submit_invoice(inv3, user=emp)
    approve_invoice(inv3, mgr)
    approve_invoice(inv3, fin)
    print(f"3  fully approved {inv3.number}: {inv3.current_state}")

    # Versioning smoke: every execution is pinned to an immutable version.
    active = invoice_workflow.active_version()
    print(
        f"4  active version: {active.version if active else None} "
        f"(executions: v{inv1.execution.workflow_version_number}, "
        f"v{inv2.execution.workflow_version_number})"
    )

    # Publish a higher-threshold revision and show new executions bind to v2
    # while already-running ones keep v1.
    publish_invoice_v2()
    inv4 = create_invoice(number=f"SMOKE-{_RUN}-24", customer_name="Acme Corp", amount="15_000.00")
    print(
        f"5  after publishing v2: active version="
        f"{invoice_workflow.active_version().version}, "
        f"running {inv1.number} stays v{inv1.execution.workflow_version_number}, "
        f"new {inv4.number} is v{invoice_execution_version(inv4)}"
    )

    # API smoke: list + detail + transition over the real demo DB
    client = APIClient()
    client.force_authenticate(mgr)
    response = client.get("/api/executions/")
    print(f"6  API list: {response.status_code}, count={response.data['count']}")

    execution_id = inv1.execution.pk
    actions = client.get(f"/api/executions/{execution_id}/actions/")
    print(f"7  API actions: {[a['name'] for a in actions.data['actions']]}")

    transition = client.post(
        f"/api/executions/{execution_id}/transition/",
        {"action": "approve", "reason": "demo smoke"},
        format="json",
    )
    print(f"8  API transition: {transition.status_code} -> {transition.data.get('current_state')}")

    # Comments + attachments: tied to the execution, visible in the timeline.
    comment = inv1.execution.add_comment(user=mgr, text="Smoke-testing the discussion layer.")
    print(f"9  comment added: id={comment.pk}, author={comment.author_label}")
    has_comment = any(e.event_type == "comment_added" for e in inv1.execution.timeline())
    print(f"10 timeline shows 'Comment added': {has_comment}")

    from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402

    attachment = inv1.execution.add_attachment(
        upload=SimpleUploadedFile("smoke.pdf", b"%PDF smoke"), user=mgr
    )
    print(
        f"11 attachment added: id={attachment.pk}, "
        f"name={attachment.name}, ext={attachment.extension}"
    )
    has_attachment = any(e.event_type == "attachment_added" for e in inv1.execution.timeline())
    print(f"12 timeline shows 'Attachment added': {has_attachment}")

    api_comments = client.get(f"/api/executions/{execution_id}/comments/")
    api_attachments = client.get(f"/api/executions/{execution_id}/attachments/")
    print(
        f"13 API comments/attachments: "
        f"{api_comments.status_code}/{len(api_comments.data)}, "
        f"{api_attachments.status_code}/{len(api_attachments.data)}"
    )

    # Phase 11 developer experience: validate + simulate the demo definition,
    # explain an unavailable action and render the graph — all without DB writes.
    from workflow_kit import explain, simulate, validate_definition  # noqa: E402
    from workflow_kit.graph import to_dot  # noqa: E402

    report = validate_definition(invoice_workflow)
    print(f"14 validation: valid={report.is_valid}, summary={report.summary()}")

    dry_run = simulate(invoice_workflow, ["submit", "approve", "approve"])
    print(f"15 simulation: terminal={dry_run.terminal}, completed={dry_run.completed}")

    explanation = explain(invoice_workflow, inv4.execution, "submit", user=emp)
    print(
        f"16 explain 'submit' on {inv4.number}: "
        f"applicable={explanation.applicable}, reasons={[r.kind for r in explanation.reasons]}"
    )

    dot = to_dot(invoice_workflow)
    print(f"17 graph: {dot.splitlines()[0]} with {dot.count('->')} edge(s)")

    # Phase 12 analytics + observability over the live demo database.
    from workflow_kit.analytics import (  # noqa: E402
        approval_metrics,
        approval_totals,
        bottlenecks,
        completion_metrics,
        execution_metrics,
        prometheus_metrics_text,
        sla_metrics,
        state_durations,
    )
    from workflow_kit.observability import correlation_id, current_correlation_id  # noqa: E402

    metrics = execution_metrics()
    completion = completion_metrics()
    approvals = approval_metrics()
    sla = sla_metrics()
    print(
        f"18 metrics: {metrics.started} started, {metrics.active} active, "
        f"{metrics.completed} completed, {metrics.sla_breached} SLA-breached; "
        f"avg completion {completion.duration.average:.1f}s; "
        f"approvals {approvals.requested} requested/{approvals.pending} pending; "
        f"SLA compliance {sla.compliance_rate}"
    )

    rows = state_durations(workflow="invoice_approval")
    print(f"19 state durations: {[(r.state, round(r.duration.average or 0)) for r in rows]}")
    flagged = [r.state for r in bottlenecks(workflow="invoice_approval") if r.is_bottleneck]
    print(f"20 bottlenecks: {flagged or 'none'}")

    by_workflow = {row["workflow"]: row for row in approval_totals(group_by="workflow")}
    print(f"21 approval totals: {by_workflow['invoice_approval']['approved']} approved")

    exposition = prometheus_metrics_text()
    sample = next(
        line
        for line in exposition.splitlines()
        if line.startswith("workflow_executions_started_total")
    )
    print(f"22 prometheus: {sample}")
    prometheus_ok = (
        exposition.startswith("# HELP") and "workflow_sla_compliance_ratio" in exposition
    )
    print(f"23 prometheus well-formed: {prometheus_ok}")

    with correlation_id("demo-smoke-correlation"):
        scoped = current_correlation_id()
        submit_invoice(_invoice("25"), user=emp)
    print(f"24 correlation id embedded: {scoped}")

    total = Invoice.objects.count()
    print(f"\nTOTAL invoices visible in demo DB: {total}")
    for number in Invoice.objects.order_by("number").values_list("number", flat=True):
        print("   -", number)
    print("\nOpen http://127.0.0.1:8000/invoices/ (login as manager) to view.")


if __name__ == "__main__":
    main()
