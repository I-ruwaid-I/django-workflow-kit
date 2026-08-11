"""Tests for the exception hierarchy.

Every workflow_kit exception must derive from ``WorkflowError`` so callers can
handle failure with a single except clause.
"""

import pytest
from workflow_kit.exceptions import (
    ConditionFailedError,
    InvalidTransitionError,
    PermissionDeniedError,
    WorkflowAlreadyCompletedError,
    WorkflowConfigurationError,
    WorkflowConflictError,
    WorkflowError,
    WorkflowNotFoundError,
)

ALL_EXCEPTIONS = [
    WorkflowConfigurationError,
    WorkflowNotFoundError,
    InvalidTransitionError,
    PermissionDeniedError,
    ConditionFailedError,
    WorkflowAlreadyCompletedError,
    WorkflowConflictError,
]


@pytest.mark.parametrize("exc", ALL_EXCEPTIONS)
def test_exceptions_derive_from_workflow_error(exc):
    assert issubclass(exc, WorkflowError)


def test_base_exception_catchable():
    with pytest.raises(WorkflowError):
        raise InvalidTransitionError("nope")
