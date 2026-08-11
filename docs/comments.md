# Comments

Comments attach free-form discussion text to a single workflow execution. They
are the discussion layer on top of state changes and approvals: participants
can ask for missing documents, note context, or record decisions without
changing workflow state.

Comments are part of the execution's history, not a separate note-taking
system. Adding a comment appends a `comment_added` audit event (see
[Audit](audit.md)) and emits a `workflow.comment_added` domain event (see
[Events](events.md)), so the discussion appears in the [timeline](timeline.md)
and is observable by notification handlers like any other workflow event.

## Adding a comment

```python
execution.add_comment(user=request.user, text="Please attach the quotation.")
```

Or through the service layer directly:

```python
from workflow_kit.comments import add_comment

comment = add_comment(execution, text="Approved in principle.", user=finance_user)
```

A comment records:

- `execution` — the workflow execution it belongs to
- `user` — the author (anonymous/system comments pass `None`)
- `text` — the comment body
- `created_at` — when it was written

## Listing comments

Comments are returned oldest first, with the author resolved:

```python
from workflow_kit.comments import execution_comments

for comment in execution_comments(execution):
    print(comment.created_at, comment.author_label, comment.text)
```

Each `WorkflowComment` also exposes `author_label`, a stable human-readable
author name that falls back to `anonymous` when no user is recorded.

## Nesting and editing

The public API is create-and-list. Comments are discussion records; there is no
reply tree and no in-place edit through the package API. If your application
needs editing or deletion, that is application policy on top of the model.

## How it fits together

1. `execution.add_comment(...)` persists the `WorkflowComment`.
2. The audit service appends a `comment_added` event to the execution's history.
3. The event system emits a `workflow.comment_added` `DomainEvent`.
4. `execution.timeline()` shows the comment as a "Comment added" entry.

Because the timeline is *derived* from the audit trail (see
[Audit](audit.md)), adding a comment automatically makes it part of the same
history that powers timelines and notifications — there is no second source of
truth.