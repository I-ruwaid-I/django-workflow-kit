"""Automation rule storage for Django Workflow Kit.

An :class:`AutomationRule` is a WHEN/IF/THEN rule that host applications can
create without writing code:

    WHEN   <event type>            e.g. "response.submitted"
    IF     <conditions>            e.g. severity == "high"
    THEN   <actions>               e.g. [{"action": "mission.create_task", ...}]

Rules are intentionally app-agnostic: the event vocabulary, condition fields
and action names are all plain strings resolved by the host application. The
kit supplies the storage, the safe evaluation and the execution plumbing.
"""

from __future__ import annotations

from django.db import models


class AutomationRule(models.Model):
    """A persistent WHEN/IF/THEN automation rule."""

    name = models.CharField(max_length=200)
    trigger = models.CharField(
        max_length=200,
        help_text=(
            "Event type this rule listens to, e.g. 'response.submitted', "
            "'workflow.transitioned' or 'task.moved'."
        ),
    )
    scope = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text=(
            "Optional opaque scope (e.g. 'survey:42'). Blank rules are global; "
            "when a host app fires an event with a scope, only rules with a "
            "matching or blank scope run."
        ),
    )
    condition = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of {field, op, value} clauses. All clauses must pass. "
            "Supported ops: eq, ne, gt, gte, lt, lte, contains, startswith, "
            "endswith, is_empty, not_empty. field is a dot path into the "
            "event context (e.g. 'payload.severity')."
        ),
    )
    actions = models.JSONField(
        default=list,
        blank=True,
        help_text="List of {action, params} actions to run when the rule fires.",
    )
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
