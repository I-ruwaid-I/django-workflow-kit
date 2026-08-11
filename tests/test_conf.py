"""Tests for package configuration loading."""

from unittest.mock import patch

import pytest
from workflow_kit.conf import WorkflowKitSettings, settings


def test_default_atomic_transitions():
    assert settings.ATOMIC_TRANSITIONS is True


def test_custom_setting_override():
    with patch(
        "django.conf.settings.WORKFLOW_KIT",
        {"ATOMIC_TRANSITIONS": False},
        create=True,
    ):
        assert settings.ATOMIC_TRANSITIONS is False


def test_unknown_setting_raises_attribute_error():
    with patch("django.conf.settings.WORKFLOW_KIT", {}, create=True):
        with pytest.raises(AttributeError) as excinfo:
            settings.__getattr__("DOES_NOT_EXIST")
        assert "DOES_NOT_EXIST" in str(excinfo.value)


def test_settings_proxy_accepts_custom_defaults():
    proxy = WorkflowKitSettings(defaults={"CUSTOM": "value"})
    assert proxy.CUSTOM == "value"
