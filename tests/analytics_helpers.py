"""Shared data builders for the Phase 12 analytics tests.

These helpers build executions through the public workflow API (so audit
events, approvals and version bindings are created the same way a real
application would produce them) and then pin timestamps for deterministic
assertions about durations, state spans and SLA breaches.
"""

from __future__ import annotations

from datetime import datetime

from workflow_kit import ApprovalMode, ApprovalRequirement, Transition, Workflow


def build_analytics_workflow() -> Workflow:
    """A workflow with one approval step and reject/cancel exits."""
    return Workflow(
        name="analytics_flow",
        initial="draft",
        states=["draft", "review", "approved", "rejected", "cancelled"],
        transitions=[
            ("submit", "draft", "review"),
            Transition("approve", "review", "approved"),
            Transition("reject", "review", "rejected"),
            Transition("cancel", "draft", "cancelled"),
        ],
        approval_requirements={
            "review": ApprovalRequirement(
                mode=ApprovalMode.ANY,
                approvers=["Manager"],
            ),
        },
    )


def run(execution, *actions, user=None):
    """Run a sequence of actions on an execution via the public API.

    ``approve`` / ``reject`` use the dedicated convenience methods; any other
    string is executed as a named transition.
    """
    for action in actions:
        if action == "approve":
            execution.approve(user=user)
        elif action == "reject":
            execution.reject(user=user)
        else:
            execution.transition(action, user=user)
    return execution


def set_timestamps(
    execution,
    *,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    current_state: str | None = None,
) -> None:
    """Pin execution timeline columns for deterministic analytics."""
    from workflow_kit.models import WorkflowExecution

    updates: dict[str, object] = {}
    if started_at is not None:
        updates["started_at"] = started_at
    if completed_at is not None:
        updates["completed_at"] = completed_at
    if current_state is not None:
        updates["current_state"] = current_state
    if updates:
        WorkflowExecution.objects.filter(pk=execution.pk).update(**updates)


def retime_events(execution, mapping) -> None:
    """Rewrite ``created_at`` on audit events selected by event type/action.

    Keys are event type strings, or ``(event_type, action)`` tuples to select a
    single transition among several.
    """
    from workflow_kit.models import WorkflowEvent

    for key, when in mapping.items():
        if isinstance(key, tuple):
            event_type, action = key
            WorkflowEvent.objects.filter(
                execution=execution, event_type=event_type, action=action
            ).update(created_at=when)
        else:
            WorkflowEvent.objects.filter(execution=execution, event_type=key).update(
                created_at=when
            )


def set_due_at(execution, due_at: datetime, /) -> None:
    """Pin the ``due_at`` deadline of the execution's review approval."""
    from workflow_kit.models import Approval

    Approval.objects.filter(execution=execution).update(due_at=due_at)


def add_user(username: str, *groups: str):
    """Create (or reuse) a user with the given group memberships."""
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group

    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={"password": "test-password-123"},
    )
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


def manager() -> object:
    """A user in the Manager group (the review approval approver)."""
    return add_user("analytics-manager", "Manager")
