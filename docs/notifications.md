# Notifications

Notifications are a **consumer** of domain events, never a concern of the
workflow engine. When the engine records a fact it emits an
[event](events.md); the notification router subscribes to those events and
hands them to providers, which build and deliver messages.

```text
Workflow Event ──► Notification Router ──► Provider ──► Email / Webhook
```

This keeps the engine decoupled: it neither knows about email addresses nor
third-party services. Adding a channel is purely a routing concern.

## Providers

A provider implements a single method:

```python
from workflow_kit.notifications import NotificationProvider

class MyProvider(NotificationProvider):
    def send(self, event) -> bool:
        ...
        return True
```

`send` receives the raw event and returns `True` on success. Providers that
cannot deliver should raise a `NotificationError`.

### Email (`EmailProvider`)

Uses Django's email infrastructure (`django.core.mail`) through the modern
`MAILERS` configuration introduced in Django 6.1, so it works with the console
mailer in development, the SMTP mailer in production and the locmem mailer in
tests. The mailer's backend is chosen by the host project's `MAILERS` setting;
the package never touches `EMAIL_BACKEND`. No third-party dependency is required.

```python
from workflow_kit.notifications import EmailProvider

EmailProvider(
    recipients=lambda event: ["owner@example.com"],   # or a static list
)
```

Subject and body can be overridden with callables that receive the event:

```python
EmailProvider(
    recipients=["owner@example.com"],
    subject_fn=lambda event: f"Approval for {event.object.display}",
    body_fn=lambda event: f"Workflow {event.workflow} changed state.",
)
```

### Webhook (`WebhookProvider`)

Posts a structured JSON payload to `WORKFLOW_KIT["WEBHOOK_URL"]`. Every request
is signed with an **HMAC-SHA256** signature over `timestamp.event_id.body`,
sent in the `X-Domain-Signature` header together with
`X-Domain-Event`, `X-Domain-Event-Id` and `X-Domain-Timestamp`, so receivers can
authenticate the sender and detect tampering or replay.

The payload contains only the public event fields — never the full business
object, credentials or internal state.

## Routing events to providers

A `NotificationRouter` subscribes to the event dispatcher and forwards matching
events:

```python
from workflow_kit.notifications import NotificationRouter

router = NotificationRouter()
router.register(email_provider, event_type="workflow.completed")
router.register(webhook_provider, event_type="*")
router.install()
```

- `install()` subscribes every registered `(event_type, provider)` pair.
- `uninstall()` removes the subscriptions.
- `clear()` unsubscribes and drops all registrations.
- Provider failures are isolated and logged — they never break the workflow.

## Configuration

Notifications are configured through the `WORKFLOW_KIT` dict in Django settings.
Defaults are provided, so basic usage needs no configuration. Email delivery
uses the host project's `MAILERS` setting (Django >= 6.1); the mailer alias is
selected with `EMAIL_MAILER`:

```python
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {"host": "smtp.example.com"},
    },
}

WORKFLOW_KIT = {
    "NOTIFICATIONS_ENABLED": True,
    "EMAIL_NOTIFICATIONS_ENABLED": True,
    "EMAIL_MAILER": "default",          # which MAILERS alias to use
    "EMAIL_FROM": "no-reply@example.com",   # falls back to DEFAULT_FROM_EMAIL
    "EMAIL_SUBJECT_PREFIX": "[Workflow] ",
    "WEBHOOK_NOTIFICATIONS_ENABLED": False,
    "WEBHOOK_URL": "https://hooks.example.com/workflow",
    "WEBHOOK_SECRET": "choose-a-secret",
}
```

Webhooks are disabled by default. `WEBHOOK_SECRET` signs every request; when
empty no signature header is added (not recommended for sensitive payloads).

## Delivery guarantees

Notification delivery follows the event system's semantics: synchronous,
best-effort, in-process. There is **no** retry policy, queue or dead-letter
mechanism yet, and the package does not claim guaranteed delivery. A failing
handler is logged and swallowed, so notifications never corrupt workflow state.
For production-grade delivery (retries, idempotency, exactly-once), run
delivery in an application-level worker (e.g. Celery) consuming the same
events.

## Demo

The Invoice Approval example wires an `[EVENT]` console logger and an email
notification on workflow completion. With the console mailer (`MAILERS`) it
prints one email; with SMTP configured it delivers the real message. This
wiring lives in the demo (`invoices/events.py`), not in the package.

## See also

- [Events](events.md): the stream notifications consume.