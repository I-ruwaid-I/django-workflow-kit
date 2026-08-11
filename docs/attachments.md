# Attachments

Attachments let participants attach files to a workflow execution — receipts,
signed documents, screenshots or export files. Files are stored through
Django's storage abstraction (`FileField`), so the package works out of the box
with Django's default local storage and with any other backend the hosting
application configures (S3, Azure, ...) by setting `DEFAULT_FILE_STORAGE`. No
third-party service is required.

## Adding an attachment

Pass any file-like object with a `name` and `size` (an `UploadedFile` from a
request, an in-memory uploaded file, ...):

```python
execution.add_attachment(upload=request.FILES["file"], user=request.user)
```

Or through the service layer:

```python
from workflow_kit.attachments import add_attachment

attachment = add_attachment(
    execution,
    upload=uploaded_file,
    name="final-quote.pdf",  # optional override of the original file name
    user=finance_user,
)
```

An attachment records:

- `execution` — the workflow execution it belongs to
- `uploaded_by` — who uploaded it (anonymous uploads pass `None`)
- `file` — the stored file (via the default storage backend)
- `name` — the display name (original file name unless overridden)
- `content_type` and `size` — captured at upload time for listing
- `created_at` — when it was uploaded

## Listing attachments

```python
from workflow_kit.attachments import execution_attachments

for attachment in execution_attachments(execution):
    print(attachment.name, attachment.size, attachment.extension)
```

`WorkflowAttachment.extension` returns the lower-cased file extension (e.g.
`pdf`, `jpg`) without the leading dot. `attachment.file.url` yields the storage
URL for rendering download links.

## Audit and events

Like comments, attachments are part of the execution's history. Uploading a
file appends an `attachment_added` audit event, emits a
`workflow.attachment_added` domain event, and appears in
`execution.timeline()` as an "Attachment added" entry — so external handlers can
watch for file uploads without reaching into the storage backend.

## Media configuration

Because attachments write through Django's `MEDIA_ROOT`, hosting applications
need the standard Django media configuration:

```python
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
```

and, in development, serve media files (typically with `static()` in `urls.py`
behind `DEBUG`). Production deployments point `DEFAULT_FILE_STORAGE` at their
object store and keep the same code.