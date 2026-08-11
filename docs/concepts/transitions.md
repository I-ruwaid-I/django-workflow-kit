# Concepts: Transitions and actions

A **transition** moves an execution between states:

```text
draft → manager_review
```

An **action** is the operation a user performs to trigger a transition:

```text
submit, approve, reject, cancel, return
```

## Transition properties

- Name
- Source state
- Target state
- Optional permission requirement
- Optional conditions
- Metadata and callbacks

A transition must fail cleanly when the source state is wrong, the user lacks
permission, a condition fails, or the workflow is inactive or completed.

See [Transitions](../transitions.md) for implementation details.