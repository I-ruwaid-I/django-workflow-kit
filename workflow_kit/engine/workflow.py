"""Workflow definitions: :class:`State`, :class:`Transition` and :class:`Workflow`.

A ``Workflow`` is a pure-Python, immutable-after-construction definition of a
process. It is validated eagerly so invalid configurations fail fast at import
time rather than at execution time.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from workflow_kit.approvals.requirements import (
    ApprovalMode,
    ApprovalRequirement,
)
from workflow_kit.conditions.base import Condition
from workflow_kit.conditions.context import ConditionContext, build_condition_context
from workflow_kit.conditions.evaluate import conditions_met
from workflow_kit.engine import registry
from workflow_kit.exceptions import (
    ConditionFailedError,
    InvalidTransitionError,
    WorkflowConfigurationError,
    WorkflowNotFoundError,
)
from workflow_kit.permissions.base import PermissionProvider
from workflow_kit.permissions.evaluate import is_authorized

if TYPE_CHECKING:
    from django.db.models import Model

    from workflow_kit.models.execution import WorkflowExecution

type _TransitionSpec = Transition | tuple[str, str, str]


def _humanize(name: str) -> str:
    """Turn a machine name such as ``manager_review`` into a display label."""
    return name.replace("_", " ").title()


def _coerce_state(state: str | State) -> State:
    if isinstance(state, State):
        return state
    return State(state)


class State:
    """A single stage in a workflow.

    ``name`` is the stable, machine-readable identifier. ``label`` is the
    human-readable display name and defaults to a prettified version of the
    name. Display labels are never used as identifiers.
    """

    __slots__ = ("name", "label")

    def __init__(self, name: str, *, label: str | None = None) -> None:
        if not name:
            raise WorkflowConfigurationError("State name must not be empty.")
        self.name = name
        self.label = label if label is not None else _humanize(name)

    def __repr__(self) -> str:
        return f"State(name={self.name!r}, label={self.label!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, State):
            return self.name == other.name
        if isinstance(other, str):
            return self.name == other
        return NotImplemented


class Transition:
    """A single allowed move between states.

    ``name`` is the action that triggers the move (e.g. ``submit``),
    ``source`` is the state the execution must be in, and ``target`` is the
    resulting state.

    ``permission`` optionally declares an authorization requirement. Supported
    values: ``None`` (no requirement), a Django permission string
    ``"app_label.codename"``, a group name, a list/tuple of the previous (all
    must pass), or a
    :class:`~workflow_kit.permissions.base.PermissionProvider` / callable.

    ``conditions`` optionally declares one or more
    :class:`~workflow_kit.conditions.base.Condition` instances. The transition
    is only available when every condition passes against the workflow's
    business object.
    """

    __slots__ = ("name", "source", "target", "label", "permission", "conditions")

    def __init__(
        self,
        name: str,
        source: str,
        target: str,
        *,
        label: str | None = None,
        permission: Any = None,
        conditions: Any = None,
    ) -> None:
        if not name:
            raise WorkflowConfigurationError("Transition name must not be empty.")
        self.name = name
        self.source = source
        self.target = target
        self.label = label if label is not None else _humanize(name)
        self.permission = permission
        self.conditions = self._coerce_conditions(conditions)
        self._validate_permission_spec(permission)

    @staticmethod
    def _coerce_conditions(conditions: Any) -> tuple[Condition, ...]:
        if conditions is None:
            return ()
        if isinstance(conditions, Condition):
            return (conditions,)
        if isinstance(conditions, (list, tuple)):
            for condition in conditions:
                if not isinstance(condition, Condition):
                    raise WorkflowConfigurationError(
                        f"Transition conditions must be Condition instances, got {condition!r}."
                    )
            return tuple(conditions)
        raise WorkflowConfigurationError(
            f"Transition conditions must be a Condition or a list of Conditions, "
            f"got {conditions!r}."
        )

    @staticmethod
    def _validate_permission_spec(permission: Any) -> None:
        _permission_types = (str, PermissionProvider)
        if permission is None or isinstance(permission, _permission_types):
            return
        if isinstance(permission, (list, tuple)):
            if not permission:
                raise WorkflowConfigurationError("Permission requirements must not be empty.")
            for requirement in permission:
                if not (isinstance(requirement, _permission_types) or callable(requirement)):
                    raise WorkflowConfigurationError(
                        f"Invalid permission requirement: {requirement!r}"
                    )
            return
        if callable(permission):
            return
        raise WorkflowConfigurationError(f"Invalid permission spec: {permission!r}")

    def __repr__(self) -> str:
        return f"Transition(name={self.name!r}, source={self.source!r}, target={self.target!r})"


class Workflow:
    """A workflow definition.

    A ``Workflow`` describes a process: its states, its single initial state
    and the transitions allowed between states. It is a template; running
    instances are represented by :class:`~workflow_kit.models.WorkflowExecution`
    objects tied to a specific business object.

    Example::

        workflow = Workflow(
            name="invoice_approval",
            initial="draft",
            states=["draft", "manager_review", "approved", "rejected"],
            transitions=[
                ("submit", "draft", "manager_review"),
                ("approve", "manager_review", "approved"),
                ("reject", "manager_review", "rejected"),
            ],
        )
    """

    def __init__(
        self,
        *,
        name: str,
        initial: str,
        states: Sequence[str | State],
        transitions: Sequence[_TransitionSpec],
        approval_requirements: Mapping[str, ApprovalRequirement] | None = None,
        register: bool = True,
    ) -> None:
        if not name:
            raise WorkflowConfigurationError("Workflow name must not be empty.")
        self.name = name
        self.initial = initial
        self._states: dict[str, State] = {}
        self._transitions_by_source: dict[str, list[Transition]] = {}
        self._transitions_by_action: dict[tuple[str, str], list[Transition]] = {}
        self._approval_requirements: dict[str, ApprovalRequirement] = {}
        self._validate_and_build(states, transitions)
        self._set_approval_requirements(approval_requirements)
        if register:
            registry.register(self)

    # -- Definition building and validation ---------------------------------

    def _validate_and_build(
        self,
        states: Sequence[str | State],
        transitions: Sequence[_TransitionSpec],
    ) -> None:
        if not states:
            raise WorkflowConfigurationError(
                f"Workflow '{self.name}' must define at least one state."
            )
        for state in states:
            state_obj = _coerce_state(state)
            if state_obj.name in self._states:
                raise WorkflowConfigurationError(
                    f"Workflow '{self.name}' defines state '{state_obj.name}' more than once."
                )
            self._states[state_obj.name] = state_obj

        if self.initial not in self._states:
            raise WorkflowConfigurationError(
                f"Workflow '{self.name}' initial state '{self.initial}' is "
                f"not among its states: {sorted(self._states)}."
            )

        seen: dict[tuple[str, str, str], str] = {}
        for spec in transitions:
            transition = self._coerce_transition(spec)
            for state_name, role in ((transition.source, "source"), (transition.target, "target")):
                if state_name not in self._states:
                    raise WorkflowConfigurationError(
                        f"Workflow '{self.name}' transition "
                        f"'{transition.name}' references unknown {role} state "
                        f"'{state_name}'."
                    )
            key = (transition.source, transition.name, transition.target)
            if key in seen:
                raise WorkflowConfigurationError(
                    f"Workflow '{self.name}' defines transition "
                    f"'{transition.name}' from '{transition.source}' to "
                    f"'{transition.target}' more than once."
                )
            seen[key] = transition.name
            self._transitions_by_source.setdefault(transition.source, []).append(transition)
            self._transitions_by_action.setdefault((transition.source, transition.name), []).append(
                transition
            )

    def _set_approval_requirements(
        self,
        requirements: Mapping[str, ApprovalRequirement] | None,
    ) -> None:
        """Attach and validate per-state approval requirements (Phase 9).

        Requirement keys must reference declared workflow states.
        """
        if requirements is None:
            return
        for state_name, requirement in requirements.items():
            if state_name not in self._states:
                unknown = sorted(self._states)
                raise WorkflowConfigurationError(
                    f"Workflow '{self.name}' declares an approval requirement for "
                    f"unknown state '{state_name}'; known states: {unknown}."
                )
            if not isinstance(requirement, ApprovalRequirement):
                raise WorkflowConfigurationError(
                    f"Workflow '{self.name}' approval requirement for '{state_name}' "
                    f"must be an ApprovalRequirement, got {requirement!r}."
                )
            self._approval_requirements[state_name] = requirement

    def approval_requirement(self, state_name: str) -> ApprovalRequirement:
        """Return the approval requirement attached to ``state_name``.

        States without an explicit requirement use the default single-approval
        rule (``ALL`` with a single unassigned slot), preserving the Phase 3
        sequential behaviour.
        """
        return self._approval_requirements.get(
            state_name,
            ApprovalRequirement(mode=ApprovalMode.ALL),
        )

    @property
    def approval_requirements(self) -> dict[str, ApprovalRequirement]:
        """The per-state approval requirements declared by the workflow."""
        return dict(self._approval_requirements)

    @staticmethod
    def _coerce_transition(spec: _TransitionSpec) -> Transition:
        if isinstance(spec, Transition):
            return spec
        name, source, target = spec
        return Transition(name, source, target)

    # -- Introspection ------------------------------------------------------

    @property
    def states(self) -> tuple[State, ...]:
        """All states in definition order."""
        return tuple(self._states.values())

    def state(self, name: str) -> State:
        """Return the state with the given name.

        Raises :class:`WorkflowNotFoundError` if the state does not exist.
        """
        try:
            return self._states[name]
        except KeyError as exc:
            raise WorkflowNotFoundError(f"Workflow '{self.name}' has no state '{name}'.") from exc

    def transitions_from(self, source: str) -> list[Transition]:
        """Return the transitions leaving ``source``, in definition order."""
        return list(self._transitions_by_source.get(source, []))

    def actions_from(self, source: str) -> list[str]:
        """Return the distinct action names leaving ``source``, in definition order."""
        return list(dict.fromkeys(t.name for t in self.transitions_from(source)))

    def transitions_for_action(self, source: str, action: str) -> list[Transition]:
        """Return the transitions for ``action`` from ``source``, in definition order.

        Multiple transitions may share an action name when their conditions
        route to different targets (conditional routing).
        """
        return list(self._transitions_by_action.get((source, action), []))

    def transition_for(self, source: str, action: str) -> Transition | None:
        """Return the first transition for ``action`` from ``source``, if any."""
        candidates = self.transitions_for_action(source, action)
        return candidates[0] if candidates else None

    def is_terminal(self, state: str) -> bool:
        """Return True if ``state`` has no outgoing transitions (terminal)."""
        return not self._transitions_by_source.get(state)

    @property
    def terminal_states(self) -> frozenset[str]:
        """Names of all states with no outgoing transitions."""
        return frozenset(name for name in self._states if self.is_terminal(name))

    # -- Execution ----------------------------------------------------------

    def _condition_context(
        self,
        execution: WorkflowExecution,
        user: Any,
    ) -> ConditionContext:
        return build_condition_context(self, execution, user=user)

    def _passing_transitions(
        self,
        execution: WorkflowExecution,
        action: str,
        *,
        user: Any,
    ) -> list[Transition]:
        """Return every transition for ``action`` whose conditions pass.

        Condition evaluation errors propagate to the caller.
        """
        context = self._condition_context(execution, user)
        return [
            transition
            for transition in self.transitions_for_action(execution.current_state, action)
            if conditions_met(transition, context)
        ]

    def resolve_transition(
        self,
        execution: WorkflowExecution,
        action: str,
        *,
        user: Any = None,
    ) -> Transition:
        """Resolve the transition to run for ``action`` on ``execution``.

        Filters the transitions for ``action`` by their conditions. A single
        surviving candidate is executed; the action is blocked when none pass,
        and ambiguous when more than one passes (raises
        :class:`~workflow_kit.exceptions.WorkflowConfigurationError`).
        :class:`InvalidTransitionError` is raised when the action does not
        exist from the current state.
        """
        candidates = self.transitions_for_action(execution.current_state, action)
        if not candidates:
            raise InvalidTransitionError(
                f"Cannot execute transition '{action}': current state is "
                f"'{execution.current_state}' in workflow '{self.name}'."
            )
        passing = self._passing_transitions(execution, action, user=user)
        if not passing:
            raise ConditionFailedError(
                f"Transition '{action}' is blocked by conditions in state "
                f"'{execution.current_state}' of workflow '{self.name}'."
            )
        if len(passing) > 1:
            targets = ", ".join(t.target for t in passing)
            raise WorkflowConfigurationError(
                f"Transition '{action}' from '{execution.current_state}' in workflow "
                f"'{self.name}' resolves to multiple passing targets "
                f"({targets}); refuse overlapping conditions on one action."
            )
        return passing[0]

    # -- Versioning (Phase 9) ----------------------------------------------

    def versions(self) -> Any:
        """Return all persisted versions of this workflow, newest first."""
        from workflow_kit.models import WorkflowVersion

        return WorkflowVersion.objects.filter(workflow=self.name).order_by("-version")

    def version(self, number: int) -> Any:
        """Return the persisted version ``number``.

        Raises :class:`WorkflowNotFoundError` when no such version exists.
        """
        from workflow_kit.exceptions import WorkflowNotFoundError as _NotFound

        version = self.versions().filter(version=number).first()
        if version is None:
            raise _NotFound(f"Workflow '{self.name}' has no version '{number}'.")
        return version

    def active_version(self) -> Any:
        """Return the active (highest published) version of this workflow."""
        from workflow_kit.engine.versioning import active_version

        return active_version(self.name)

    def create_version(
        self,
        from_version: Any = None,
        *,
        user: Any = None,
        changelog: str = "",
    ) -> Any:
        """Create a new DRAFT version of this workflow (version number = max + 1).

        ``from_version`` (an int or :class:`WorkflowVersion`) optionally seeds
        the new draft from an existing version; otherwise the current registered
        definition is snapshotted.
        """
        from workflow_kit.engine.versioning import create_workflow_version

        return create_workflow_version(
            self,
            from_version=from_version,
            user=user,
            changelog=changelog,
        )

    def publish_version(self, version: Any = None, *, user: Any = None, changelog: str = "") -> Any:
        """Validate and publish ``version`` (int or :class:`WorkflowVersion`)."""
        from workflow_kit.engine.versioning import publish_version
        from workflow_kit.models import WorkflowVersion

        if not isinstance(version, WorkflowVersion):
            version = self.version(version)
        return publish_version(version, user=user, changelog=changelog)

    def retire_version(self, version: Any = None, *, user: Any = None, reason: str = "") -> Any:
        """Retire a published ``version`` so new executions stop selecting it."""
        from workflow_kit.engine.versioning import retire_version
        from workflow_kit.models import WorkflowVersion

        if not isinstance(version, WorkflowVersion):
            version = self.version(version)
        return retire_version(version, user=user, reason=reason)

    def update_version(
        self,
        version: Any,
        definition: Any,
        *,
        user: Any = None,
        changelog: str = "",
    ) -> Any:
        """Replace a DRAFT version's definition (``Workflow`` or snapshot dict)."""
        from workflow_kit.engine.versioning import update_version
        from workflow_kit.models import WorkflowVersion

        if not isinstance(version, WorkflowVersion):
            version = self.version(version)
        return update_version(version, definition, user=user, changelog=changelog)

    def start(
        self,
        obj: Model,
        *,
        user: Any = None,
        version: Any = None,
        allow_unpublished: bool = False,
    ) -> WorkflowExecution:
        """Start a new execution of this workflow for ``obj``.

        The execution begins in the workflow's initial state. Raises
        :class:`WorkflowNotFoundError` if an execution already exists for
        ``obj``. ``user`` is optionally recorded as the initiator so self-approval
        rules can be enforced.

        ``version`` optionally pins the execution to a specific version (an int
        or :class:`WorkflowVersion`). Without it the active published version is
        selected; with no versions the execution stays unversioned (legacy
        behaviour). ``allow_unpublished`` explicitly permits draft/retired
        versions for development/testing.
        """
        from workflow_kit.engine.execution import start_execution

        return start_execution(
            self,
            obj,
            user=user,
            version=version,
            allow_unpublished=allow_unpublished,
        )

    def get_execution(self, obj: Model) -> WorkflowExecution:
        """Return the execution of this workflow for ``obj``.

        Raises :class:`WorkflowNotFoundError` if no execution exists.
        """
        from workflow_kit.engine.execution import get_execution

        return get_execution(self, obj)

    def current_state(self, execution: WorkflowExecution) -> str:
        """Return the current state of ``execution``."""
        return execution.current_state

    def available_actions(
        self,
        execution: WorkflowExecution,
        user: Any = None,
    ) -> list[str]:
        """Return the actions available to ``user`` from the current state.

        An action is available only when exactly one of its transitions has
        passing conditions (unambiguous routing) and the user is authorized for
        that transition. Without a ``user``, only unprotected transitions are
        returned.
        """
        grouped: dict[str, list[Transition]] = {}
        for transition in self.transitions_from(execution.current_state):
            grouped.setdefault(transition.name, []).append(transition)

        allowed: set[str] = set()
        for name, candidates in grouped.items():
            passing = [
                candidate
                for candidate in candidates
                if conditions_met(candidate, self._condition_context(execution, user))
            ]
            if len(passing) == 1 and is_authorized(user, self, execution, passing[0]):
                allowed.add(name)
        ordered = [t.name for t in self.transitions_from(execution.current_state)]
        return [name for name in dict.fromkeys(ordered) if name in allowed]

    def can_transition(
        self,
        execution: WorkflowExecution,
        action: str,
        user: Any = None,
    ) -> bool:
        """Return True if ``action`` is valid for ``execution``'s state.

        Structural validity, unambiguous conditional routing and authorization
        for ``user`` are all checked.
        """
        if self.is_terminal(execution.current_state):
            return False
        if not self.transitions_for_action(execution.current_state, action):
            return False
        passing = self._passing_transitions(execution, action, user=user)
        if len(passing) != 1:
            return False
        return is_authorized(user, self, execution, passing[0])

    def transition(
        self,
        execution: WorkflowExecution,
        action: str,
        *,
        user: Any = None,
    ) -> WorkflowExecution:
        """Execute ``action`` against ``execution`` and return it.

        The state change is applied atomically. Raises
        :class:`InvalidTransitionError` for actions that are not valid from the
        current state, :class:`ConditionFailedError` when every candidate
        transition is blocked by its conditions, :class:`PermissionDeniedError`
        for unauthorized actions and :class:`WorkflowAlreadyCompletedError`
        when the workflow has reached a terminal state.
        """
        from workflow_kit.engine.execution import execute_transition

        return execute_transition(self, execution, action, user=user)

    def __repr__(self) -> str:
        return (
            f"Workflow(name={self.name!r}, initial={self.initial!r}, "
            f"states={len(self._states)}, transitions="
            f"{sum(len(t) for t in self._transitions_by_source.values())})"
        )
