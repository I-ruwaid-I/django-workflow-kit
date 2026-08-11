"""Testing utilities for Django Workflow Kit.

Phase 11 adds reusable helpers so application test suites can verify workflow
behaviour in a few lines: a validation assertion mixin, execution-state
assertion helpers and deterministic workflow fixtures. They live in
``workflow_kit.testing`` and are dependency-light (pure Python).

Example::

    from workflow_kit.testing import WorkflowValidationMixin, workflow_factory

    class TestInvoices(WorkflowValidationMixin):
        def test_submission(self):
            workflow = self.assert_valid_workflow(workflow_factory("invoice"))
            ...
"""

from workflow_kit.testing.factories import (
    SimpleWorkflow,
    workflow_factory,
    workflow_module,
)
from workflow_kit.testing.mixins import (
    ExecutionAssertions,
    WorkflowValidationMixin,
)

__all__ = [
    "WorkflowValidationMixin",
    "ExecutionAssertions",
    "workflow_factory",
    "workflow_module",
    "SimpleWorkflow",
]
