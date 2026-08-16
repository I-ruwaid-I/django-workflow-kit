"""Automation for Django Workflow Kit.

The kit provides a generic WHEN/IF/THEN automation layer:

* :class:`~workflow_kit.models.automation.AutomationRule` stores rules.
* :func:`workflow_kit.automation.fire` evaluates and runs rules for an event.
* :func:`workflow_kit.automation.actions.register` lets host apps add actions.
"""

from workflow_kit.automation.actions import get, names, register, unregister
from workflow_kit.automation.evaluate import clause_passes, conditions_met
from workflow_kit.automation.engine import fire, install, on_event

__all__ = [
    "fire",
    "install",
    "on_event",
    "register",
    "unregister",
    "get",
    "names",
    "conditions_met",
    "clause_passes",
]
