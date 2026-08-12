"""Smoke tests verifying the Django app bootstraps correctly."""

import workflow_kit
from django.apps import apps
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from workflow_kit.apps import WorkflowKitConfig
from workflow_kit.models import WorkflowExecution


def test_version_is_semver():
    assert len(workflow_kit.__version__.split(".")) == 3
    assert workflow_kit.__version__ == "1.0.0"


def test_app_is_installed():
    assert apps.is_installed("workflow_kit")


def test_app_config_meta():
    config = apps.get_app_config("workflow_kit")
    assert isinstance(config, WorkflowKitConfig)
    assert config.name == "workflow_kit"
    assert config.label == "workflow_kit"


def test_view_analytics_permission_is_provisioned(db):
    content_type = ContentType.objects.get_for_model(WorkflowExecution)
    permission = Permission.objects.get(
        content_type=content_type,
        codename="view_analytics",
    )
    assert permission.name == "Can view workflow analytics"
