"""Shared pytest fixtures for the Django Workflow Kit test suite."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from tests.test_project.demo.models import Invoice


@pytest.fixture
def user_factory():
    """Create Django users with a deterministic username."""

    User = get_user_model()

    def _create(username: str = "alice", **kwargs) -> get_user_model():
        return User.objects.create_user(username=username, **kwargs)

    return _create


@pytest.fixture
def user(user_factory):
    """A standard test user."""
    return user_factory()


@pytest.fixture
def invoice(user) -> Invoice:
    """A minimal invoice attached to a workflow owner."""
    return Invoice.objects.create(
        number="INV-1001",
        amount="1500.00",
        vendor="Acme Ltd",
    )


@pytest.fixture
def analytics_workflow():
    """A registered workflow with a single approval step for analytics tests."""
    from workflow_kit.engine import registry

    from tests.analytics_helpers import build_analytics_workflow

    workflow = build_analytics_workflow()
    yield workflow
    registry.unregister("analytics_flow")
