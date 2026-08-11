# Approvals

The approval engine is a thin, transactional layer over the workflow engine.
A pending :class:`~workflow_kit.models.Approval` guards each non-terminal
state an execution reaches; deciding it (approved or rejected) is what moves
the execution forward.

## How approvals are created

Each time an execution enters a non-terminal state, the engine creates one
`Approval` for that step:

```
draft
  │  submit
  ▼
manager_review   ◄── Approval[manager_review] PENDING
  │  approve (Manager)
  ▼
finance_review   ◄── Approval[finance_review] PENDING
  │  approve (Finance)
  ▼
approved         ◄── terminal (no approval)
```

The initial state never creates an approval.

A workflow may declare per-step requirements to create one approval *per
approver slot* on a step. See [Parallel approvals](#parallel-approvals) below.

## Deciding an approval

The approval API is available directly on the execution:

```python
execution.pending_approvals()   # approvals waiting for a decision
execution.approve(user)         # approve the current pending step
execution.reject(user, reason="Missing quotation")   # reject it
```

Both methods:

- run inside an atomic transaction and re-read the execution row with
  `select_for_update` (so simultaneous decisions cannot double-advance),
- enforce the transition's `permission` through the Phase 2 permission
  system — the approval layer never decides permissions itself,
- persist the decision on the `Approval` (status, approver, action, reason),
- record audit events (`approval_approved` / `approval_rejected`) **and**
  the state transition atomically.

```python
approval = execution.approve(manager)
approval.status        # "APPROVED"
approval.approver      # <User: manager>
approval.action        # "approve"
approval.reason        # ""

approval = execution.reject(manager, reason="Missing quotation")
approval.status        # "REJECTED"
approval.reason        # "Missing quotation"
```

## Sequencing

Because deciding a step applies the workflow transition, reaching the next
non-terminal state creates the next pending approval automatically. Sequential
approval is therefore purely a workflow-state concern:

```python
execution.approve(manager)      # manager_review -> finance_review
execution.approve(finance)      # finance_review -> approved (completed)
```

## Parallel approvals

Phase 9 lets a workflow declare a :class:`ApprovalMode` and a list of
approvers per step instead of the default one-slot approval. The step then
creates one pending approval per approver slot, and the step advances only
when the requirement is satisfied.

```python
from workflow_kit import ApprovalMode, ApprovalRequirement, Workflow

Workflow(
    ...,
    approval_requirements={
        # ALL: every slot must approve before the step advances
        "executive_review": ApprovalRequirement(
            mode=ApprovalMode.ALL,
            approvers=["Executive", "Finance"],
        ),
        # ANY: the first decision (approve or reject) settles the step
        "expense_review": ApprovalRequirement(
            mode=ApprovalMode.ANY,
            approvers=["Manager", "Finance"],
        ),
        # QUORUM: quorum approvals advance the step; a single rejection vetoes
        "board_vote": ApprovalRequirement(
            mode=ApprovalMode.QUORUM,
            quorum=2,
            approvers=["Manager", "Finance", "Executive"],
        ),
    },
)
```

Approvers are resolved at step-entry time. Each entry in `approvers` may be a
group name (any member matches), a username, a user instance, an
:class:`ApproverResolver` subclass, or a callable returning any of the above.
Leaving `approvers` empty produces a single `ANY` slot any authenticated user
can fill — the default behaviour of the sequential engine.

Voting rules per mode:

- **`ALL`** — advances only after every slot approves; any single rejection
  rejects the execution.
- **`ANY`** — the first decision (approve or reject) settles the step;
  remaining slots are cancelled.
- **`QUORUM`** — advances once `quorum` slots approved; a single rejection
  vetoes, and when the remaining pending slots can no longer reach the quorum
  the step rejects as well.

Deciding a slot is the same `execution.approve(user)` /
`execution.reject(user)` API; the engine routes the user to the matching
pending slot. A user who already decided a slot of the step cannot decide it
again (`ApprovalNotPendingError`). When a step advances, the still-pending
sibling approvals are cancelled and recorded as `approval_cancelled`.

### Self-approval

Each requirement accepts `allow_self`. When `False`, the initiation user (set
via `workflow.start(obj, user=...)` and stored on
`WorkflowExecution.initiated_by`) cannot decide the step.

## Delegation

`execution.delegate(...)` forwards one approver's slot to another user. The
grantee can then decide the step, and the engine authorizes the decision
against the **granter's** rights (permission, groups), never the grantee's.

```python
execution.delegate(
    granter=finance,
    grantee=payables_lead,
    step="finance_review",     # empty: every pending step of the execution
    reason="Finance on leave",
    expires_at=None,           # optional expiry
)
```

Delegations are recorded in the `WorkflowDelegation` model and visible on the
timeline (`approval_delegated`). Calling `delegation.revoke()` deactivates a
delegation (`delegation_revoked`); expired delegations no longer authorize a
decision.

## Escalation

`execution.escalate(approver, user=..., reason=...)` reroutes the current step
to a single escalation approver: the step's pending approvals are cancelled
and replaced by one `ANY`-mode approval (with `assignment["escalated"] = True`)
that the escalation approver alone decides.

```python
execution.escalate("Executive", user=manager, reason="Urgent override")
```

The escalation actor (`user`) must be authorized for the step's `approve`
transition, and a step may be escalated only while it has pending approvals.
The resulting approval is decided like any other.

## SLA tracking

Each requirement may set `sla` (a `timedelta`). The engine stores the deadline
on each `Approval.due_at`:
`due_at = created_at + sla`. Helper APIs are available:

```python
from workflow_kit.approvals import overdue_approvals

overdue_approvals()                  # global query
overdue_approvals(execution=exec)    # scoped to an execution
approval.is_overdue                  # property on a single Approval
```

## Errors & guarantees

- `ApprovalNotPendingError` — no pending approval exists for the current step,
  or the acting user has no pending slot on it (and no active delegation).
- `PermissionDeniedError` — the acting user is not authorized (state is
  untouched, the approval stays `PENDING`), or self-approval is forbidden, or
  an unauthenticated user tries to decide.
- `InvalidTransitionError` — the current state has no such transition.
- `WorkflowAlreadyCompletedError` — a decision is attempted after the
  execution reached a terminal state.
- Repeated decisions are refused: once a step is decided (or the workflow
  completed), a second decision raises instead of double-advancing.
- All decisions are concurrency-safe: the execution row and the target
  approval are locked with `select_for_update` inside a transaction, so two
  simultaneous decisions cannot double-advance a step.