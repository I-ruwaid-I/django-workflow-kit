# Security

Security is a primary requirement of the package. Workflows, conditions and
permissions are configured in Python — never stored as executable code in the
database, and never evaluated through `eval`/`exec`. Django authorization is
always respected; the admin and the dashboard can never bypass transition
permissions.

For the vulnerability disclosure policy see [`SECURITY.md`](../SECURITY.md).

## Phase 13 security audit

The Phase 13 audit (`tests/test_phase13_security.py`, 15 tests) verifies the
authorization and data-hygiene boundary across every surface:

**API authorization**

- Unauthenticated requests are denied on every execution endpoint.
- Write methods (transition, comment, attachment) are not exposed as unguarded
  routes; an unauthorized user cannot transition an execution through the API.
- Error responses never leak internal details or stack traces.

**Object and tenant isolation**

- Arbitrary business-object fields are never rendered over HTTP — objects are
  exposed only as `{type, id}`.
- Actions and approvals are scoped by the engine's permission evaluation.

**Logging and webhooks**

- Structured log payloads contain no request payload fields, so
  passwords/tokens are never written to logs.
- Webhook payloads contain no secrets (signing headers use a key that is never
  part of the body).

**Attachments**

- Uploaded file names are sanitized against absolute paths and path traversal.
- `ATTACHMENT_MAX_SIZE` (default `0` = unlimited) caps upload size.
- `ATTACHMENT_ALLOWED_CONTENT_TYPES` (default empty = allow all) is an
  allow-list for upload content types.
- `ATTACHMENT_PUBLIC_URLS` (default `False`) controls whether the REST API
  exposes the stored file's `url`; when `False` no storage URL is leaked.
- Violations raise `workflow_kit.exceptions.AttachmentError`.

**Admin**

- All registered workflow models are read-only (no add / change / delete) so
  the admin can never bypass workflow authorization; non-staff users are
  denied the admin entirely.

**Version immutability**

- Published (and retired) workflow versions reject mutation through the ORM,
  so a running execution's pinned definition cannot be silently altered.

## Dashboard permissions

- Every dashboard page requires an authenticated user.
- Aggregate analytics (Overview metrics, Analytics screens) require staff or
  the `workflow_kit.view_analytics` permission — the same rule as the REST
  analytics endpoints. Non-viewers see the Overview with a permission notice
  and their own pending actions, never aggregate numbers.
- My Work derives its list from the persisted `Approval` assignment records,
  so a user only sees decisions they are genuinely authorized to make.

## Never do

- Never pass untrusted input to `eval()` or arbitrary code execution paths.
- Never configure conditions or workflows from database-stored code.
- Never bypass transition permissions in admin, API, analytics or dashboard
  code.
