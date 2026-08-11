"""Optional Django REST Framework integration.

This package only loads when ``djangorestframework`` is installed. The REST API
is a thin HTTP layer over the existing workflow engine: it never re-implements
authorization, conditions, approvals or state changes. Installing the core
package never requires DRF — use the ``drf`` extra explicitly:

    pip install django-workflow-kit[drf]

Include :mod:`workflow_kit.api.urls` in a project's URL configuration to expose
the execution endpoints.
"""
