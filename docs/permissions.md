# Permissions

*(Planned for Phase 2.)*

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