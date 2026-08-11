"""ORM model for versioned workflow definitions (Phase 9).

A ``WorkflowVersion`` persists a point-in-time snapshot of a workflow
definition so that:

- workflow identity (``workflow`` name) stays a logical concept;
- every execution binds exactly one version at start and never changes it;
- published versions are immutable.

The definition is stored as a JSON snapshot built by
:func:`workflow_kit.engine.versioning.serialize_workflow`. Only definitions
that can be represented safely in JSON (built-in conditions, string
permission specs, string approver assignments) are eligible for versioning;
anything else keeps the legacy, definition-in-Python behaviour.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import models

from workflow_kit.exceptions import WorkflowVersionError

if TYPE_CHECKING:
    from workflow_kit.engine.workflow import Workflow


class VersionStatus(models.TextChoices):
    """The lifecycle states of a workflow version."""

    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    RETIRED = "RETIRED", "Retired"


class WorkflowVersion(models.Model):
    """An immutable, numbered snapshot of one workflow definition.

    ``workflow`` holds the workflow identity (its registered name), ``version``
    the monotonic per-workflow number and ``definition`` the serialized
    definition. Lifecycle transitions follow:

    .. code-block:: text

        DRAFT -> PUBLISHED -> RETIRED

    Published (and retired) versions are immutable through the ORM: modifying
    their definition, workflow or version number is rejected by ``save()``.
    """

    workflow = models.CharField(max_length=200, db_index=True)
    version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=VersionStatus.choices,
        default=VersionStatus.DRAFT,
        db_index=True,
    )
    definition = models.JSONField(default=dict, blank=True)
    changelog = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="wk_created_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["workflow", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "version"],
                name="unique_version_per_workflow",
            )
        ]
        indexes = [
            models.Index(fields=["workflow", "status"]),
            models.Index(fields=["workflow", "-version"]),
        ]

    def __str__(self) -> str:
        return f"{self.workflow} v{self.version} ({self.status})"

    # -- Status helpers -------------------------------------------------------

    @property
    def is_draft(self) -> bool:
        """True while the version is still an editable draft."""
        return self.status == VersionStatus.DRAFT

    @property
    def is_published(self) -> bool:
        """True once the version became available for new executions."""
        return self.status == VersionStatus.PUBLISHED

    @property
    def is_retired(self) -> bool:
        """True once the version was retired from new executions."""
        return self.status == VersionStatus.RETIRED

    def as_workflow(self) -> Workflow:
        """Reconstruct the :class:`~workflow_kit.engine.workflow.Workflow` this version stores.

        The reconstruction is validated against the workflow's own
        configuration rules; an invalid snapshot raises
        :class:`~workflow_kit.exceptions.WorkflowVersionError`.
        """
        from workflow_kit.engine.versioning import get_version_workflow

        return get_version_workflow(self)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Enforce version lifecycle invariants on every write.

        - Draft versions may be edited freely.
        - Published versions are immutable except for retirement.
        - Retired versions are immutable.
        """
        if self.pk is not None:
            previous = WorkflowVersion.objects.get(pk=self.pk)
            if previous.status == VersionStatus.RETIRED:
                if self.status != VersionStatus.RETIRED:
                    raise WorkflowVersionError(
                        "A retired workflow version cannot be republished or edited."
                    )
                raised = (
                    self.workflow != previous.workflow
                    or self.version != previous.version
                    or self.definition != previous.definition
                )
                if raised:
                    raise WorkflowVersionError(
                        f"Retired workflow version '{previous}' is immutable."
                    )
            elif previous.status == VersionStatus.PUBLISHED:
                if self.status not in (VersionStatus.PUBLISHED, VersionStatus.RETIRED):
                    raise WorkflowVersionError(
                        "A published workflow version can only be retired, never "
                        "editing its definition, re-versioned or reverted to draft."
                    )
                raised = (
                    self.workflow != previous.workflow
                    or self.version != previous.version
                    or self.definition != previous.definition
                )
                if raised:
                    raise WorkflowVersionError(
                        f"Published workflow version '{previous}' is immutable."
                    )
        return super().save(*args, **kwargs)
