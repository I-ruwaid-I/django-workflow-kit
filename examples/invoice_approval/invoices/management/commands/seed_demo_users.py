"""Command to seed the demo roles, users and permissions.

Creates the ``Employee``, ``Manager``, ``Finance`` and ``Executive`` groups as
well as one canonical user per role so the permission-protected invoice
workflow can be exercised through the UI. Idempotent: safe to run multiple
times.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group as AuthGroup
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from invoices.models import Invoice

DEFAULT_PASSWORD = "demo-password-123"

ROLE_GROUPS = {
    "employee": ["Employee"],
    "manager": ["Manager"],
    "finance": ["Finance"],
    "executive": ["Executive"],
}

USER_PERMISSIONS = {
    "manager": ["can_reject_invoice"],
    "finance": ["can_finalize_invoice", "can_reject_invoice"],
    "executive": ["can_finalize_invoice", "can_reject_invoice"],
}


class Command(BaseCommand):
    help = "Create the demo groups and users for the invoice approval workflow."

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        content_type = ContentType.objects.get_for_model(Invoice)
        permissions = {
            perm.codename: perm for perm in Permission.objects.filter(content_type=content_type)
        }

        for username, group_names in ROLE_GROUPS.items():
            user = self._get_or_create_user(User, username)
            groups = {AuthGroup.objects.get_or_create(name=name)[0] for name in group_names}
            user.groups.set(groups)
            for codename in USER_PERMISSIONS.get(username, []):
                perm = permissions.get(codename)
                if perm is not None:
                    user.user_permissions.add(perm)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded demo users (password: {DEFAULT_PASSWORD}): {', '.join(ROLE_GROUPS)}"
            )
        )

    @staticmethod
    def _get_or_create_user(User, username: str):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"is_staff": False, "is_superuser": False},
        )
        if created:
            user.set_password(DEFAULT_PASSWORD)
            user.save()
        return user
