"""Pluggable action registry for automation rules.

Host applications register named actions (e.g. ``mission.create_task``,
``notify.mission_user``) and the engine invokes them by name when a rule
fires. The kit never knows what an action does — that stays in the app.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# name -> callable(context: dict, params: dict) -> Any
_ACTIONS: dict[str, Callable[[dict[str, Any], dict[str, Any]], Any]] = {}


def register(name: str, handler: Callable[[dict[str, Any], dict[str, Any]], Any]) -> None:
    """Register ``handler`` under ``name`` (idempotent overwrite)."""
    _ACTIONS[name] = handler


def unregister(name: str) -> None:
    _ACTIONS.pop(name, None)


def get(name: str) -> Callable[[dict[str, Any], dict[str, Any]], Any] | None:
    return _ACTIONS.get(name)


def names() -> list[str]:
    return sorted(_ACTIONS)
