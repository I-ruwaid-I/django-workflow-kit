# Timeline

The timeline is a structured, user-facing view of an execution's history. It
never stores its own data — it derives from the [audit trail](audit.md), so
there is a single source of truth for workflow activity.

## Reading the timeline

```python
timeline = execution.timeline()

for event in timeline:
    event.label       # "Approved" (human-friendly, from event_type)
    event.event_type  # "approval_approved"
    event.timestamp   # datetime
    event.actor       # username of the actor, or None
    event.source_state
    event.target_state
    event.reason      # e.g. the rejection reason
    event.metadata    # dict
```

`TimelineEvent` is a frozen dataclass value object exported from the package
top level (`from workflow_kit import TimelineEvent`), so applications render
it however they like — the package never returns pre-formatted strings only.

## Example

For a full approval lifecycle the timeline reads:

```
Workflow started
State changed
Approval required
Approved
State changed
Approval required
Approved
State changed
Workflow completed
```

Discussion events (Phase 10) appear in the same chronological stream: adding a
comment shows `Comment added` and uploading a file shows `Attachment added`,
both derived from the `comment_added` / `attachment_added` audit events. See
[Comments](comments.md) and [Attachments](attachments.md).

Ordering is chronological (by event timestamp, then primary key), matching the
underlying audit trail exactly.