# Permissions

Permissions integrate with Django's permission system:

- Django model permissions
- Groups
- Users
- Custom permission classes

```python
Transition(
    name="approve",
    source="finance_review",
    target="approved",
    permission="finance.approve_invoice",
)
```

Authorization is checked before a transition is committed.

## Analytics permission

The package provisions `workflow_kit.view_analytics` during migrations. Grant
it to users or groups that should see aggregate analytics in the REST API and
dashboard:

```python
from django.contrib.auth.models import Permission

permission = Permission.objects.get(
    content_type__app_label="workflow_kit",
    content_type__model="workflowexecution",
    codename="view_analytics",
)
group.permissions.add(permission)
```

Staff users can also view analytics. Ordinary authenticated users can still
use execution-level dashboard pages, but they do not see aggregate metrics
unless they hold this permission.
