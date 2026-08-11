"""Smoke tests verifying the Django app bootstraps correctly."""

import workflow_kit
from django.apps import apps
from workflow_kit.apps import WorkflowKitConfig


def test_version_is_semver():
    assert len(workflow_kit.__version__.split(".")) == 3
    assert workflow_kit.__version__ == "0.4.0"


def test_app_is_installed():
    assert apps.is_installed("workflow_kit")


def test_app_config_meta():
    config = apps.get_app_config("workflow_kit")
    assert isinstance(config, WorkflowKitConfig)
    assert config.name == "workflow_kit"
    assert config.label == "workflow_kit"
