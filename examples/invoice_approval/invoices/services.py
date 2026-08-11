"""Service layer for invoice actions.

The service layer lives here instead of the views. Every action is driven
through the public API; the demo never mutates workflow state directly.
"""

from __future__ import annotations

from workflow_kit.engine.versioning import ensure_workflow_version

from .models import Invoice
from .workflow import build_invoice_workflow, invoice_workflow


def ensure_invoice_workflow_version() -> None:
    """Publish version 1 of the invoice workflow on first use (idempotent).

    Without this the demo would run unversioned (legacy definition-in-Python
    behaviour). Publishing a version once means every execution is pinned to a
    numbered, immutable definition snapshot.
    """
    ensure_workflow_version(invoice_workflow)


def create_invoice(
    *,
    number: str,
    customer_name: str,
    amount: str | int | float,
    description: str = "",
) -> Invoice:
    """Create an invoice and start its workflow in the initial state."""
    ensure_invoice_workflow_version()
    invoice = Invoice.objects.create(
        number=number,
        customer_name=customer_name,
        amount=amount,
        description=description,
    )
    invoice_workflow.start(invoice)
    return invoice


def publish_invoice_v2(*, user=None) -> None:
    """Publish version 2 of the invoice workflow with a higher threshold.

    Demonstrates Phase 9 versioning: a new immutable definition (same name,
    higher ``executive_threshold`` of 25_000) is snapshotted as DRAFT, revised,
    then published. New executions bind to version 2; executions already
    running keep the version (and thus the routing rules) they started with.
    """
    v1 = invoice_workflow.active_version()
    draft = invoice_workflow.create_version(from_version=v1)
    revised = build_invoice_workflow(executive_threshold=25_000, register=False)
    invoice_workflow.update_version(draft, revised, changelog="Raise executive threshold to 25_000")
    invoice_workflow.publish_version(
        draft, user=user, changelog="Raise executive threshold to 25_000"
    )


def invoice_execution_version(invoice: Invoice):
    """Return the pinned version number of an invoice's execution, if any."""
    return invoice_workflow.get_execution(invoice).workflow_version_number


def _transition(invoice: Invoice, action: str, user: object) -> None:
    execution = invoice_workflow.get_execution(invoice)
    invoice_workflow.transition(execution, action, user=user)


def submit_invoice(invoice: Invoice, user=None) -> None:
    """Submit an invoice, moving it from draft to manager review."""
    _transition(invoice, "submit", user)


def approve_invoice(invoice: Invoice, user=None, *, reason: str = "") -> None:
    """Approve the current review stage through the approval decision API.

    The decision is persisted on the step's :class:`Approval` record and
    recorded in the audit trail together with the state transition.
    """
    execution = invoice_workflow.get_execution(invoice)
    execution.approve(user, reason=reason)


def reject_invoice(invoice: Invoice, user=None, *, reason: str = "") -> None:
    """Reject the current review stage through the approval decision API.

    The rejection reason is persisted on the approval and in the audit trail.
    """
    execution = invoice_workflow.get_execution(invoice)
    execution.reject(user, reason=reason)


def delegate_invoice(
    invoice: Invoice,
    *,
    granter,
    grantee,
    step: str = "",
    reason: str = "",
) -> None:
    """Forward ``granter``'s approval right to ``grantee`` for ``step``.

    Demonstrates Phase 9 delegation: the grantee can then decide the step and
    the engine authorizes the decision against the granter's rights.
    """
    execution = invoice_workflow.get_execution(invoice)
    execution.delegate(granter=granter, grantee=grantee, step=step, reason=reason)


def escalate_invoice(
    invoice: Invoice,
    *,
    approver,
    user=None,
    reason: str = "",
) -> None:
    """Escalate the current step to a single escalation ``approver``.

    Demonstrates Phase 9 escalation: the step's pending approvals are cancelled
    and replaced by one any-of approval the escalation approver alone decides.
    ``user`` is recorded as the escalation actor.
    """
    execution = invoice_workflow.get_execution(invoice)
    execution.escalate(approver, user=user, reason=reason)


def add_invoice_comment(invoice: Invoice, *, text: str, user=None):
    """Attach ``text`` as a comment on the invoice's execution.

    Demonstrates Phase 10 comments: the discussion shows up in the execution
    timeline as a ``comment_added`` audit event.
    """
    execution = invoice_workflow.get_execution(invoice)
    return execution.add_comment(user=user, text=text)


def attach_invoice_file(invoice: Invoice, *, upload, user=None):
    """Attach ``upload`` to the invoice's execution.

    Demonstrates Phase 10 attachments: the file is stored through Django's
    default storage backend and recorded in the audit trail / timeline.
    """
    execution = invoice_workflow.get_execution(invoice)
    return execution.add_attachment(upload=upload, user=user)
