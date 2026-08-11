"""ORM model for workflow executions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from workflow_kit.engine.workflow import Workflow
    from workflow_kit.models.approval import Approval
    from workflow_kit.models.history import WorkflowEvent
    from workflow_kit.timeline.event import TimelineEvent


class WorkflowExecution(models.Model):
    """A running instance of a workflow bound to a specific business object.

    The workflow *definition* lives in Python (see
    :class:`workflow_kit.engine.workflow.Workflow`); this model persists only
    the runtime state of an execution: which workflow it belongs to, the
    object it runs against and its current state.

    ``workflow_version`` optionally pins the exact definition snapshot the
    execution started with (Phase 9). When set, every later resolution (state
    machine, conditions, approvals, permissions, audit, events) uses that
    version, never the live registered definition.
    """

    workflow_name = models.CharField(max_length=200, db_index=True)
    workflow_version = models.ForeignKey(
        "workflow_kit.WorkflowVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="executions",
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    object = GenericForeignKey("content_type", "object_id")

    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="wk_executions",
    )
    current_state = models.CharField(max_length=100)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["workflow_name", "workflow_version"]),
            # current_state is filtered by the REST execution list and the
            # analytics ``state`` scopes; started_at drives the default
            # ``-started_at`` ordering of the same list and the analytics
            # started-at range filter.
            models.Index(fields=["current_state"]),
            models.Index(fields=["-started_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["workflow_name", "content_type", "object_id"],
                name="unique_execution_per_workflow_and_object",
            )
        ]

    def __str__(self) -> str:
        return f"{self.workflow_name} #{self.object_id} -> {self.current_state}"

    @property
    def workflow(self) -> Workflow:
        """Resolve the workflow definition for this execution.

        When the execution carries a ``workflow_version``, the definition is
        reconstructed from that immutable version so transitions, conditions,
        approvals and permissions never silently switch to a newer published
        definition. Unversioned executions keep the live registered definition.
        """
        from workflow_kit.engine.versioning import get_workflow_for_execution

        return get_workflow_for_execution(self)

    @property
    def workflow_version_number(self) -> int | None:
        """The version number the execution is pinned to, if any.

        Falls back to the workflow's active version when the execution was
        started before versions existed.
        """
        if self.workflow_version_id:
            return self.workflow_version.version if self.workflow_version else None
        return None

    @property
    def is_completed(self) -> bool:
        """True once the execution has reached a terminal state."""
        return self.completed_at is not None

    @property
    def state_label(self) -> str:
        """The human-readable label of the current state."""
        return self.workflow.state(self.current_state).label

    def available_actions(self, user: Any = None) -> list[str]:
        """Wrap ``Workflow.available_actions`` for this execution."""
        return self.workflow.available_actions(self, user=user)

    def can_transition(self, action: str, user: Any = None) -> bool:
        """Wrap ``Workflow.can_transition`` for this execution."""
        return self.workflow.can_transition(self, action, user=user)

    def transition(self, action: str, *, user: Any = None) -> WorkflowExecution:
        """Wrap ``Workflow.transition`` for this execution."""
        return self.workflow.transition(self, action, user=user)

    # -- Approvals (Phase 3) ----------------------------------------------

    def pending_approvals(self) -> QuerySet[Approval]:
        """Return the approvals still waiting for a decision."""
        from workflow_kit.approvals.service import pending_approvals

        return pending_approvals(self)

    def approve(self, user: Any = None, *, reason: str = "") -> Approval:
        """Approve the current pending step and advance the execution.

        Authorization is delegated to the workflow's permission system.
        Returns the updated :class:`~workflow_kit.models.approval.Approval`.
        """
        from workflow_kit.approvals.service import approve_execution

        return approve_execution(self, user=user, reason=reason)

    def reject(self, user: Any = None, *, reason: str = "") -> Approval:
        """Reject the current pending step with an optional ``reason``.

        Authorization is delegated to the workflow's permission system. The
        reason is persisted on the approval and in the audit trail.
        Returns the updated :class:`~workflow_kit.models.approval.Approval`.
        """
        from workflow_kit.approvals.service import reject_execution

        return reject_execution(self, user=user, reason=reason)

    # -- Phase 9: escalation and delegation -----------------------------------

    def escalate(
        self,
        approver: Any,
        *,
        user: Any = None,
        reason: str = "",
    ) -> Approval:
        """Escalate the current step to a single escalation ``approver``.

        The step's pending approvals are cancelled and replaced by one approval
        the escalation approver alone can decide (any-of). ``user`` is recorded
        as the escalation actor and must be authorized for the step's approve
        transition.
        """
        from workflow_kit.approvals.service import escalate_execution

        return escalate_execution(self, approver=approver, user=user, reason=reason)

    def delegate(
        self,
        *,
        granter: Any,
        grantee: Any,
        reason: str = "",
        step: str = "",
        expires_at: Any = None,
    ) -> Any:
        """Forward ``granter``'s approval right on ``step`` to ``grantee``.

        Returns the new :class:`~workflow_kit.models.delegation.WorkflowDelegation`.
        """
        from workflow_kit.approvals.service import delegate_approval

        return delegate_approval(
            self,
            granter=granter,
            grantee=grantee,
            reason=reason,
            step=step,
            expires_at=expires_at,
        )

    # -- Audit and timeline (Phase 3) --------------------------------------

    def history(self) -> QuerySet[WorkflowEvent]:
        """Return the ordered audit trail for this execution."""
        from workflow_kit.audit.service import event_history

        return event_history(self)

    def timeline(self) -> list[TimelineEvent]:
        """Return the structured, ordered timeline for this execution."""
        from workflow_kit.timeline.service import execution_timeline

        return execution_timeline(self)

    # -- Comments and attachments (Phase 10) ---------------------------------

    def add_comment(self, user: Any = None, *, text: str) -> Any:
        """Attach a comment to this execution and record it in the timeline.

        ``user`` is recorded as the author. A ``comment_added`` audit event is
        appended and a ``workflow.comment_added`` domain event is emitted.
        Returns the new :class:`~workflow_kit.models.comment.WorkflowComment`.
        """
        from workflow_kit.comments.service import add_comment

        return add_comment(self, text=text, user=user)

    def add_attachment(self, upload: Any, *, name: str | None = None, user: Any = None) -> Any:
        """Persist ``upload`` as an attachment on this execution.

        The file is stored through Django's default storage backend and an
        ``attachment_added`` audit event / domain event is emitted.
        Returns the new :class:`~workflow_kit.models.attachment.WorkflowAttachment`.
        """
        from workflow_kit.attachments.service import add_attachment

        return add_attachment(self, upload=upload, name=name, user=user)
