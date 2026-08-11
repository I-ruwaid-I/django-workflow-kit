"""Phase 12 tests: structured observability and correlation ids.

Covers the correlation-id context machinery (set/reset/generated values) and
the :class:`StructuredEventLogger` integration with the existing event
dispatcher: install/uninstall semantics, structured payload extras and
correlation propagation through a real transition.
"""

from __future__ import annotations

import logging

import pytest
from workflow_kit.observability import (
    correlation_id,
    current_correlation_id,
    install_structured_logging,
    reset_correlation_id,
    set_correlation_id,
    uninstall_structured_logging,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _restore_logging_state():
    """Each test starts from a clean install state and restores it."""
    was_installed = uninstall_structured_logging()
    yield
    if was_installed:
        install_structured_logging()


def test_correlation_id_is_none_by_default():
    assert current_correlation_id() is None


def test_correlation_id_explicit_value():
    token = set_correlation_id("req-42")
    try:
        assert current_correlation_id() == "req-42"
    finally:
        reset_correlation_id(token)
    assert current_correlation_id() is None


def test_correlation_id_context_generates_uuid():
    with correlation_id() as value:
        assert value
        assert current_correlation_id() == value
    assert current_correlation_id() is None


def test_correlation_id_nested_scopes_restore():
    with correlation_id("outer"):
        with correlation_id("inner"):
            assert current_correlation_id() == "inner"
        assert current_correlation_id() == "outer"
    assert current_correlation_id() is None


def test_install_is_idempotent(caplog):
    first = install_structured_logging()
    second = install_structured_logging()
    assert first is second
    uninstall_structured_logging()
    assert uninstall_structured_logging() is False


def test_structured_logger_logs_payload(caplog, analytics_workflow, invoice):
    log = logging.getLogger(f"workflow_kit.test.{__name__}")
    install_structured_logging(log=log, correlation_provider=lambda: "rid-007")

    caplog.set_level(logging.INFO, logger=log.name)
    with correlation_id("rid-007"):
        workflow = analytics_workflow
        workflow.start(invoice)

    records = [r for r in caplog.records if r.name == log.name]
    assert records
    payload = records[-1].workflow_event
    assert payload["event"] == "workflow.started"
    assert payload["workflow"] == "analytics_flow"
    assert payload["object_type"] == "demo.invoice"
    assert payload["correlation_id"] == "rid-007"


def test_uninstall_stops_logging_events(caplog, analytics_workflow, invoice):
    log = logging.getLogger(f"workflow_kit.test.{__name__}")
    install_structured_logging(log=log)
    assert uninstall_structured_logging() is True

    caplog.set_level(logging.INFO, logger=log.name)
    analytics_workflow.start(invoice)

    records = [r for r in caplog.records if r.name == log.name]
    assert records == []
