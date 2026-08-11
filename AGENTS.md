# Django Workflow Kit — OpenCode Master Build Instructions

## 0. IMPORTANT: START FROM ZERO

This project does not exist yet.

You are responsible for creating the complete project from an empty directory.

Do NOT assume that:

- A Git repository exists
- A Python project exists
- `pyproject.toml` exists
- Django is installed
- Tests exist
- Documentation exists
- CI exists
- Package structure exists

Create everything required.

The final result must be a professional, publishable open-source Python/Django package.

---

# 1. Project Identity

Project name:

**Django Workflow Kit**

PyPI package:

```text
django-workflow-kit
```

Python import:

```python
workflow_kit
```

Repository:

```text
django-workflow-kit
```

Short description:

> A modern, extensible workflow and approval engine for Django applications.

Primary goal:

Build a production-quality Django workflow engine that allows developers to create:

- State machines
- Approval workflows
- Multi-step approvals
- Conditional workflows
- Parallel approvals
- Audit trails
- Timelines
- Comments
- Delegation
- Escalation
- SLA tracking
- Notifications
- Workflow analytics

---

# 2. PRODUCT VISION

Django developers should be able to add a sophisticated workflow system to an existing Django project without building the workflow engine themselves.

The package should follow this philosophy:

> **Simple to start. Powerful when needed. Django-native.**

A basic workflow should take only a few minutes to implement.

Advanced enterprise functionality should be available without forcing complexity onto simple projects.

---

# 3. FIRST TASK — CREATE THE PROJECT

Start by creating the complete repository.

Expected high-level structure:

```text
django-workflow-kit/
│
├── workflow_kit/
├── tests/
├── examples/
├── docs/
├── scripts/
│
├── .github/
│   └── workflows/
│
├── .gitignore
├── .editorconfig
├── LICENSE
├── README.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
├── AGENTS.md
├── pyproject.toml
└── Makefile
```

The exact structure can evolve if there is a strong architectural reason.

---

# 4. INITIALIZE GIT

Initialize a Git repository.

Create an appropriate `.gitignore` for:

- Python
- Django
- Virtual environments
- IDEs
- OS files
- Coverage
- Build artifacts

Do NOT commit:

```text
.venv/
__pycache__/
*.pyc
.pytest_cache/
.coverage
dist/
build/
*.egg-info/
.env
```

Create the initial repository structure before implementing functionality.

---

# 5. PYTHON PROJECT

Use modern Python packaging.

Use:

```text
pyproject.toml
```

Do NOT use an old-style `setup.py` unless there is a compelling reason.

Target:

```text
Python >= 3.11
Django >= 5.0
```

The package should support modern Django versions without depending unnecessarily on Django internals.

---

# 6. CORE DEPENDENCY PHILOSOPHY

The core package must remain lightweight.

Required:

```text
Python
Django
```

Optional integrations should use extras.

Potential future extras:

```text
[drf]
[celery]
[redis]
[docs]
```

Do not make:

- Django REST Framework
- Celery
- Redis
- PostgreSQL
- Redis clients
- Cloud SDKs

mandatory dependencies unless absolutely necessary.

---

# 7. CREATE A VIRTUAL ENVIRONMENT

For development, create a virtual environment if the environment allows it.

Example:

```bash
python -m venv .venv
```

Install development dependencies.

The project must be runnable using a clean development environment.

---

# 8. DEVELOPMENT TOOLING

Configure appropriate modern tooling.

Preferred:

- Ruff
- Pytest
- pytest-django
- Coverage
- MyPy where practical
- Pre-commit
- GitHub Actions

Do not introduce tools merely because they are fashionable.

Every tool must have a useful purpose.

---

# 9. CORE PACKAGE STRUCTURE

Create:

```text
workflow_kit/
│
├── __init__.py
├── apps.py
├── conf.py
├── exceptions.py
│
├── models/
│   ├── __init__.py
│   ├── workflow.py
│   ├── state.py
│   ├── transition.py
│   ├── execution.py
│   ├── approval.py
│   ├── history.py
│   ├── comment.py
│   └── delegation.py
│
├── engine/
│   ├── __init__.py
│   ├── workflow.py
│   ├── execution.py
│   ├── transition.py
│   └── context.py
│
├── conditions/
│   ├── __init__.py
│   ├── base.py
│   └── builtin.py
│
├── permissions/
│   ├── __init__.py
│   └── base.py
│
├── approvals/
│   ├── __init__.py
│   └── service.py
│
├── audit/
│   ├── __init__.py
│   └── service.py
│
├── timeline/
│   ├── __init__.py
│   └── service.py
│
├── notifications/
│   ├── __init__.py
│   ├── base.py
│   └── registry.py
│
├── signals/
│   └── __init__.py
│
├── admin/
│   └── __init__.py
│
├── api/
│   └── __init__.py
│
├── migrations/
│   └── __init__.py
│
└── tests/
```

Do not create unnecessary empty files just to match the structure.

---

# 10. ARCHITECTURE

The architecture should conceptually be:

```text
Django Application
       │
       ▼
Workflow Definition
       │
       ▼
Workflow Engine
       │
       ├── States
       ├── Transitions
       ├── Conditions
       ├── Permissions
       ├── Approvals
       ├── Audit
       ├── Timeline
       └── Notifications
       │
       ▼
Django ORM
```

The workflow engine must remain independent from specific business models.

It must work with arbitrary Django models.

---

# 11. CORE CONCEPTS

Implement these concepts cleanly.

## Workflow

Defines the process.

Example:

```text
Invoice Approval
```

## State

Represents the current stage.

Example:

```text
draft
manager_review
finance_review
approved
rejected
```

## Transition

Moves an execution between states.

Example:

```text
draft → manager_review
```

## Action

An operation performed by a user.

Examples:

```text
submit
approve
reject
cancel
return
```

## Workflow Execution

Represents a workflow running against a specific business object.

Example:

```text
Invoice #INV-1001
Workflow: Invoice Approval
State: finance_review
```

## Approval

Represents an approval requirement or decision.

## History

Immutable record of workflow events.

---

# 12. DEVELOPER EXPERIENCE

The public API must be extremely easy to understand.

Target API:

```python
workflow.current_state()

workflow.available_actions(user)

workflow.can_transition(
    "approve",
    user,
)

workflow.transition(
    "approve",
    user=user,
)
```

Convenience methods may exist:

```python
workflow.submit(user)

workflow.approve(user)

workflow.reject(
    user,
    reason="Missing quotation",
)
```

But the generic transition mechanism must remain the foundation.

---

# 13. WORKFLOW DEFINITION API

Create a clean declarative Python API.

Target example:

```python
from workflow_kit import Workflow

invoice_workflow = Workflow(
    name="invoice_approval",
    initial="draft",
    states=[
        "draft",
        "manager_review",
        "finance_review",
        "approved",
        "rejected",
    ],
    transitions=[
        ("submit", "draft", "manager_review"),
        ("approve", "manager_review", "finance_review"),
        ("approve", "finance_review", "approved"),
        ("reject", "*", "rejected"),
    ],
)
```

The syntax may be improved if necessary.

Developer readability is more important than preserving this exact syntax.

---

# 14. STATE MACHINE

Support:

- Initial state
- Normal states
- Terminal states
- Human-readable labels
- Stable state identifiers

Example:

```python
State(
    name="manager_review",
    label="Manager Review",
)
```

Never use human-readable labels as the canonical identifier.

---

# 15. TRANSITIONS

A transition should support:

- Name
- Source
- Target
- Permission
- Conditions
- Metadata
- Callbacks/hooks where appropriate

Example:

```python
Transition(
    name="approve",
    source="manager_review",
    target="finance_review",
)
```

A transition must fail when:

- Source state is incorrect
- User lacks permission
- Condition fails
- Workflow is inactive
- Execution is already completed

Use clear custom exceptions.

---

# 16. TRANSACTION SAFETY

Workflow transitions must be atomic.

Use Django transactions.

Example:

```python
from django.db import transaction
```

A transition should not partially execute.

For example, this must not happen:

```text
State updated
     ↓
Audit failed
     ↓
Database left inconsistent
```

Design transition execution so related changes happen safely.

---

# 17. CONCURRENCY

Account for simultaneous actions.

Example:

```text
User A → approve

User B → reject
```

at almost the same time.

The engine must prevent inconsistent state.

Use appropriate database-level locking or optimistic concurrency strategies.

Do not rely solely on Python checks.

Add tests for concurrency behavior where practical.

---

# 18. PERMISSIONS

Integrate naturally with Django.

Support:

- Django permissions
- Groups
- Users
- Custom permission classes

Example:

```python
Transition(
    name="approve",
    source="finance_review",
    target="approved",
    permission="finance.approve_invoice",
)
```

Authorization must happen before the transition is committed.

---

# 19. CONDITIONS

Conditions must be extensible.

Example:

```python
class Condition:
    def evaluate(self, context) -> bool:
        ...
```

Support future conditions such as:

```text
amount > 10000
customer.is_verified
user belongs to Finance
invoice.age > 30 days
```

IMPORTANT:

Never execute arbitrary user-provided Python.

Never use unrestricted:

```python
eval(...)
```

for workflow conditions.

Security is mandatory.

---

# 20. APPROVAL SYSTEM

Design the architecture to support:

### Sequential approval

```text
Manager
 ↓
Finance
 ↓
CEO
```

### Parallel approval

```text
Manager ─┐
         ├──→ CEO
Finance ─┘
```

### Any-of

```text
Manager OR Finance
```

### All-of

```text
Manager AND Finance
```

Build sequential approval first.

Do not prematurely implement complex parallel execution.

---

# 21. AUDIT SYSTEM

Every important workflow event must be auditable.

Capture:

```text
workflow
execution
object
action
source_state
target_state
user
timestamp
reason
metadata
```

Audit history should be append-only through the public API.

Do not silently modify historical records.

---

# 22. TIMELINE

Provide:

```python
workflow.timeline()
```

Timeline should contain:

```text
Created
Submitted
Manager Approved
Moved to Finance
Rejected
Comment Added
Delegated
Escalated
```

Do not create a second independent source of truth.

Timeline should primarily derive from workflow history/events.

---

# 23. COMMENTS

Provide:

```python
workflow.add_comment(
    user=user,
    text="Please attach the quotation.",
)
```

Store:

- User
- Text
- Timestamp
- Execution

---

# 24. ATTACHMENTS

Attachments are part of the future design.

Use Django's storage abstraction.

Do not require:

- AWS
- Azure
- Google Cloud

The package must work with Django's default storage.

---

# 25. NOTIFICATIONS

Create a provider architecture.

Example:

```python
class NotificationProvider:
    def send(self, event, context):
        ...
```

Do not make third-party notification services mandatory.

Future integrations can become separate packages.

Example:

```text
django-workflow-kit-slack
django-workflow-kit-teams
django-workflow-kit-webhooks
```

---

# 26. EVENTS

Define internal events such as:

```text
workflow_started
workflow_completed
workflow_failed
state_changed
transition_executed
approval_created
approval_completed
workflow_rejected
workflow_cancelled
```

Use Django signals where appropriate.

Signals must not be the only mechanism for critical workflow execution.

---

# 27. DJANGO ADMIN

Provide useful admin integration.

Admin should eventually show:

- Workflows
- Executions
- Current state
- History
- Approvals
- Comments

Admin operations must not bypass workflow authorization.

---

# 28. REST API

REST API support must remain optional.

Do not make Django REST Framework a core dependency.

If DRF support is implemented:

```text
workflow_kit.api
```

should only load when DRF is installed.

Potential API:

```text
GET    /workflows/
GET    /workflows/{id}/
GET    /executions/
GET    /executions/{id}/
POST   /executions/{id}/transition/
GET    /executions/{id}/timeline/
POST   /executions/{id}/comments/
```

---

# 29. DATABASE

Use Django ORM and migrations.

Potential models:

```text
Workflow
WorkflowState
WorkflowTransition
WorkflowExecution
WorkflowHistory
Approval
WorkflowComment
WorkflowAttachment
WorkflowDelegation
```

Not every concept must become a database model.

Keep configuration in Python when appropriate.

---

# 30. GENERIC MODEL SUPPORT

The package must work with arbitrary Django business models.

Examples:

```text
Invoice
PurchaseOrder
LeaveRequest
ExpenseClaim
Document
Application
```

Do not build the package around Invoice specifically.

Invoice is only the demonstration model.

---

# 31. TEST PROJECT

Create a dedicated Django test project.

Example:

```text
tests/
└── test_project/
    ├── manage.py
    ├── settings.py
    └── demo/
        ├── models.py
        └── ...
```

Create realistic test models.

At minimum:

```python
class Invoice(models.Model):
    number = models.CharField(max_length=100)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )
```

---

# 32. TESTING

Use:

```text
pytest
pytest-django
coverage
```

Target:

```text
90%+ coverage
```

Test:

- State creation
- Workflow validation
- Valid transitions
- Invalid transitions
- Permissions
- Conditions
- Approvals
- Audit
- Timeline
- Comments
- Transactions
- Concurrency
- Exceptions

Do not write tests merely to increase coverage percentage.

Tests must verify behavior.

---

# 33. DOCUMENTATION

Create:

```text
docs/
├── installation.md
├── quickstart.md
├── concepts/
├── workflows/
├── states.md
├── transitions.md
├── approvals.md
├── permissions.md
├── conditions.md
├── audit.md
├── notifications.md
├── admin.md
├── api.md
├── troubleshooting.md
└── contributing.md
```

Documentation must be written as the project develops.

Do not postpone documentation until the end.

---

# 34. README

Create a professional README.

Include:

- Project overview
- Problem being solved
- Installation
- Quickstart
- Example
- Features
- Architecture
- Documentation
- Testing
- Contribution
- License
- Roadmap

The first example should be understandable without reading the rest of the documentation.

---

# 35. EXAMPLE APPLICATION

Create a polished example application.

Primary example:

# Invoice Approval System

Workflow:

```text
Draft
 ↓
Manager Review
 ↓
Finance Review
 ↓
Approved
 ↓
Paid
```

Demonstrate:

- Permissions
- Approval
- Rejection
- Comments
- Timeline
- Audit history
- Conditional routing based on invoice amount

Example:

```text
Amount <= 10,000
        ↓
Manager
        ↓
Approved

Amount > 10,000
        ↓
Manager
        ↓
Finance
        ↓
Approved
```

---

# 36. SECONDARY EXAMPLES

Eventually demonstrate:

## Leave Request

```text
Draft
 ↓
Manager
 ↓
HR
 ↓
Approved
```

## Purchase Order

```text
Draft
 ↓
Manager
 ↓
Finance
 ↓
CEO
```

## Document Verification

```text
Uploaded
 ↓
Review
 ↓
Verified
```

---

# 37. FUTURE FEATURES

Design the architecture so these can be added later:

- Parallel approval
- Any-of approval
- All-of approval
- Delegation
- Escalation
- SLA
- Reminders
- Workflow versioning
- Analytics
- REST API
- Webhooks
- Celery integration
- Redis integration
- Visual workflow designer
- React components
- BPMN import/export

DO NOT implement these all during the MVP.

---

# 38. MVP SCOPE

The first release should focus on:

```text
Workflow
   ↓
States
   ↓
Transitions
   ↓
Permissions
   ↓
Execution
   ↓
Approvals
   ↓
Audit
   ↓
Timeline
   ↓
Comments
```

The MVP must be stable before advanced functionality is added.

---

# 39. PHASED DEVELOPMENT

## Phase 0 — Project Bootstrap

Create:

- Git repository
- Python project
- pyproject.toml
- Package structure
- Django app
- Test infrastructure
- CI
- README
- LICENSE
- CHANGELOG
- CONTRIBUTING
- SECURITY
- AGENTS

Run the initial test suite.

---

## Phase 1 — Core Engine

Implement:

- Workflow
- State
- Transition
- Execution
- Current state
- Transition validation
- Exceptions
- Transactions

Tests required.

---

## Phase 2 — Permissions

Implement:

- Django permissions
- Groups
- Custom permission interface

Tests required.

---

## Phase 3 — Approval Engine

Implement:

- Approval steps
- Approve
- Reject
- Sequential approval
- Approval history

Tests required.

---

## Phase 4 — Audit & Timeline

Implement:

- History
- Audit events
- Timeline
- Comments

Tests required.

---

## Phase 5 — Django Admin

Implement useful admin integration.

Tests required where practical.

---

## Phase 6 — Conditions

Implement:

- Condition interface
- Built-in conditions
- Conditional transitions
- Secure evaluation

Tests required, especially security tests.

---

## Phase 7 — Notifications

Implement:

- Notification interface
- Django email
- Webhook

Third-party services remain optional.

---

## Phase 8 — REST API

Add optional DRF integration.

---

## Phase 9 — Advanced Workflows

Implement:

- Parallel approval
- Any-of
- All-of
- Delegation
- Escalation
- SLA

Only after the previous phases are stable.

---

# 40. CODE QUALITY

Use:

- Ruff
- Pytest
- Coverage
- Type hints
- GitHub Actions
- Pre-commit

Public classes/functions must have documentation.

Use clear naming.

Avoid excessive abstraction.

---

# 41. EXCEPTIONS

Create meaningful exceptions.

At minimum:

```text
WorkflowError
WorkflowConfigurationError
InvalidTransitionError
PermissionDeniedError
ConditionFailedError
WorkflowNotFoundError
WorkflowAlreadyCompletedError
```

Exceptions must be useful to developers.

---

# 42. LOGGING

Use Python's logging framework.

Never use:

```python
print(...)
```

for library behavior.

Never log:

- Passwords
- Tokens
- Secrets
- Sensitive personal information

---

# 43. CONFIGURATION

Use:

```python
WORKFLOW_KIT = {
    ...
}
```

in Django settings.

Basic usage must require little or no configuration.

Provide sensible defaults.

---

# 44. PERFORMANCE

Avoid:

- N+1 queries
- Unnecessary database writes
- Repeated workflow loading
- Duplicate permission checks

Use appropriate indexes.

Profile important operations if necessary.

---

# 45. SECURITY

Security is a primary requirement.

Never:

```python
eval(user_input)
```

Never execute arbitrary Python stored in the database.

Validate external input.

Respect Django authorization.

Do not bypass permissions in admin/API code.

---

# 46. PACKAGE API

Keep the public API small.

Only expose stable, intentional public objects through:

```python
workflow_kit.__init__
```

Do not make every internal class part of the public API.

Internal implementation may change.

---

# 47. SEMANTIC VERSIONING

Follow:

```text
MAJOR.MINOR.PATCH
```

Before 1.0:

```text
0.x
```

After 1.0:

Breaking API change:

```text
2.0.0
```

Feature:

```text
1.1.0
```

Bug fix:

```text
1.0.1
```

---

# 48. PYPI READINESS

Before publishing, verify:

```bash
python -m build
```

and:

```bash
twine check dist/*
```

The package must build cleanly.

Verify:

- Package imports correctly
- Metadata is correct
- README renders correctly
- License is included
- Dependencies are correct
- Wheels/sdist contain required files

Do not publish to PyPI until the package passes the release checklist.

Use TestPyPI first.

---

# 49. GITHUB ACTIONS

Create CI workflows for:

- Tests
- Lint
- Type checking
- Package build

Test against supported Python/Django versions where practical.

Example matrix:

```text
Python 3.11
Python 3.12
Python 3.13
```

and supported Django versions.

Do not claim support for versions that have not been tested.

---

# 50. CONTRIBUTING

Create contribution documentation explaining:

- Development setup
- Running tests
- Formatting
- Linting
- Creating features
- Creating tests
- Pull request expectations

---

# 51. CHANGELOG

Use a standard changelog.

Example:

```text
## Unreleased

### Added

### Changed

### Fixed

### Security
```

Keep it updated for user-facing changes.

---

# 52. AI CODING RULES

You are an AI coding agent.

Follow these rules strictly.

## Rule 1

Do not attempt to implement the entire project in one operation.

Build phase-by-phase.

## Rule 2

Before major implementation, inspect the current repository.

## Rule 3

Before changing architecture, explain why the change is necessary.

## Rule 4

Do not add dependencies without justification.

## Rule 5

Every core feature requires tests.

## Rule 6

Run tests after meaningful changes.

## Rule 7

Fix failing tests rather than hiding them.

## Rule 8

Do not delete tests merely because they fail.

## Rule 9

Do not create fake implementations.

For example:

```python
pass
```

is not an implementation.

## Rule 10

Do not leave TODO placeholders for core functionality and consider the phase complete.

## Rule 11

Keep public APIs stable once established.

## Rule 12

Update documentation alongside implementation.

## Rule 13

Do not implement future roadmap features unless explicitly requested.

## Rule 14

Prefer simple solutions.

## Rule 15

Think like an open-source maintainer, not a one-off application developer.

---

# 53. DEVELOPMENT LOOP

For every phase:

```text
Inspect
  ↓
Design
  ↓
Implement
  ↓
Test
  ↓
Fix
  ↓
Document
  ↓
Review
  ↓
Commit
```

Do not skip testing.

Do not skip documentation.

---

# 54. GIT COMMIT STYLE

Use conventional commit-style messages.

Examples:

```text
feat: bootstrap django workflow kit
feat: add workflow state engine
feat: add transition validation
feat: add permission checks
feat: add approval engine
test: add transition tests
fix: prevent duplicate workflow transitions
docs: add quickstart guide
refactor: simplify workflow execution
```

Keep commits focused.

---

# 55. FIRST COMMAND

When this instruction file is provided to you in an empty directory:

1. Inspect the directory.
2. Confirm that the project is starting from zero.
3. Create the project structure.
4. Initialize Git.
5. Create `pyproject.toml`.
6. Create the Django package.
7. Create the test infrastructure.
8. Create CI configuration.
9. Create initial documentation.
10. Run tests.
11. Report what was created.
12. Do NOT begin advanced workflow implementation yet.

---

# 56. THEN BEGIN PHASE 1

After the bootstrap is complete:

Implement only the **Core Workflow Engine**.

The first milestone is:

```text
Workflow
    ↓
State
    ↓
Transition
    ↓
Execution
```

The following must work:

```python
workflow.current_state()

workflow.can_transition(
    "submit",
    user,
)

workflow.transition(
    "submit",
    user=user,
)
```

Demonstrate this with the Invoice example.

---

# 57. DEFINITION OF SUCCESS

The project is successful when a fresh Django developer can do:

```bash
pip install django-workflow-kit
```

define a workflow such as:

```text
Draft
 ↓
Manager Review
 ↓
Finance Review
 ↓
Approved
```

and execute it using a small, understandable Python API.

The package should hide workflow complexity behind a clean interface.

---

# 58. PRODUCT STANDARD

Do not build this as a toy project.

Build it as if thousands of Django developers may eventually depend on it.

Every important decision should answer:

> Would I trust this package in a production Django application?

If not, improve it.

---

# 59. FINAL PRINCIPLE

The core philosophy of Django Workflow Kit is:

```text
Simple API
     +
Django-native architecture
     +
Strong workflow engine
     +
Excellent documentation
     +
Minimal dependencies
     +
Production reliability
```

The complexity should live **inside Django Workflow Kit**, not inside the user's application.

Start from zero.

Build carefully.

Test everything.

Document everything.

Do not rush the PyPI release.