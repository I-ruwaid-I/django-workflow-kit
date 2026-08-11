"""Invoice approval workflow definition.

This module is the single home for the invoice workflow: a ``Workflow`` built
with only the public API of ``django-workflow-kit``. The ``Invoice`` model,
services and views reference this single definition instead of manipulating a
status field directly.

Authorization is enforced by the engine, not by the UI. Each transition carries
a ``permission`` spec:

- ``"Employee"`` and ``"Manager"`` are group names (any group member passes);
- ``"invoices.can_finalize_invoice"`` / ``"invoices.can_reject_invoice"`` are
  Django permissions checked with ``user.has_perm``;
- the ``Invoice`` ``Meta.permissions`` define the canonical permission catalog;
- a superuser bypasses authorization on every transition.

The ``approve`` action from ``finance_review`` demonstrates conditional
routing: invoices up to ``executive_threshold`` are finalized directly, while
larger invoices are routed to ``executive_review`` for an extra approval step.
The engine re-evaluates the conditions against the live invoice at decision
time.

``executive_review`` demonstrates a Phase 9 parallel (all-of) approval: it
carries an :class:`~workflow_kit.approvals.requirements.ApprovalRequirement`
that assigns one pending approval to a member of the ``Executive`` group and a
second to a member of the ``Finance`` group. The execution only advances once
*both* slots are decided. Delegation and escalation are available through the
``execution.delegate(...)`` / ``execution.escalate(...)`` methods exposed as
``delegate_invoice`` / ``escalate_invoice`` in :mod:`invoices.services`.

Versioning (Phase 9): the definition is built through
:func:`build_invoice_workflow`, which takes the routing threshold as a
parameter. :data:`invoice_workflow` is the base (version 1) definition. The
demo publishes it as version 1 on first use and :mod:`invoices.services`
publishes a version 2 with a higher threshold to show that new executions bind
to the new version while already-running executions keep the definition they
started with.

Run ``python manage.py seed_demo_users`` to create the demo accounts (see the
demo README for the credentials and the resulting role matrix).
"""

from workflow_kit import (
    ApprovalMode,
    ApprovalRequirement,
    GreaterThan,
    LessThanOrEqual,
    State,
    Transition,
    Workflow,
)

WORKFLOW_NAME = "invoice_approval"

_DEFAULT_EXECUTIVE_THRESHOLD = 10_000


def build_invoice_workflow(
    *,
    executive_threshold: int = _DEFAULT_EXECUTIVE_THRESHOLD,
    register: bool = True,
) -> Workflow:
    """Build the invoice approval ``Workflow``.

    ``executive_threshold`` controls the conditional routing at Finance Review:
    invoices up to it are finalized directly, larger invoices require the extra
    Executive Review step. Publishing a version built with a different
    threshold is how the demo evolves the workflow while keeping running
    executions pinned to their original definition.

    ``register`` controls whether the built definition is registered in the
    engine registry under its name (defaults to ``True``). Version snapshots
    built purely to publish a revision must pass ``register=False`` so they do
    not replace the live registered definition.
    """
    return Workflow(
        name=WORKFLOW_NAME,
        initial="draft",
        states=[
            State("draft", label="Draft"),
            State("manager_review", label="Manager Review"),
            State("finance_review", label="Finance Review"),
            State("executive_review", label="Executive Review"),
            State("approved", label="Approved"),
            State("rejected", label="Rejected"),
        ],
        approval_requirements={
            "executive_review": ApprovalRequirement(
                mode=ApprovalMode.ALL,
                approvers=["Executive", "Finance"],
            ),
        },
        transitions=[
            Transition(
                "submit",
                "draft",
                "manager_review",
                label="Submit",
                permission="Employee",
            ),
            Transition(
                "approve",
                "manager_review",
                "finance_review",
                label="Approve",
                permission="Manager",
            ),
            Transition(
                "approve",
                "finance_review",
                "approved",
                label="Finalize",
                permission="invoices.can_finalize_invoice",
                conditions=[LessThanOrEqual("amount", executive_threshold)],
            ),
            Transition(
                "approve",
                "finance_review",
                "executive_review",
                label="Escalate to Executive",
                permission="invoices.can_finalize_invoice",
                conditions=[GreaterThan("amount", executive_threshold)],
            ),
            Transition(
                "approve",
                "executive_review",
                "approved",
                label="Finalize",
                permission="invoices.can_finalize_invoice",
            ),
            Transition(
                "reject",
                "manager_review",
                "rejected",
                label="Reject",
                permission="invoices.can_reject_invoice",
            ),
            Transition(
                "reject",
                "finance_review",
                "rejected",
                label="Reject",
                permission="invoices.can_reject_invoice",
            ),
            Transition(
                "reject",
                "executive_review",
                "rejected",
                label="Reject",
                permission="invoices.can_reject_invoice",
            ),
        ],
        register=register,
    )


invoice_workflow = build_invoice_workflow()
