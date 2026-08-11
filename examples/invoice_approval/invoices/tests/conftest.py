"""Shared fixtures for the Invoice Approval demo tests."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command

pytestmark = pytest.mark.django_db


@pytest.fixture
def demo_users():
    """Provide the seeded demo accounts (see ``manage.py seed_demo_users``)."""
    from django.contrib.auth import get_user_model

    call_command("seed_demo_users", verbosity=0)
    User = get_user_model()
    return {
        "employee": User.objects.get(username="employee"),
        "manager": User.objects.get(username="manager"),
        "finance": User.objects.get(username="finance"),
        "executive": User.objects.get(username="executive"),
    }


@pytest.fixture
def anonymous_user():
    return AnonymousUser()


@pytest.fixture
def employee_client(client, demo_users):
    client.force_login(demo_users["employee"])
    return client


@pytest.fixture
def manager_client(client, demo_users):
    client.force_login(demo_users["manager"])
    return client


@pytest.fixture
def finance_client(client, demo_users):
    client.force_login(demo_users["finance"])
    return client
