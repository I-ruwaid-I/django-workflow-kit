# Troubleshooting

## Test database / migrations errors

Run migrations for the test project before running tests:

```bash
python -m pytest
```

`pytest-django` builds the test database automatically from the demo app
migrations in `tests/test_project/demo/migrations`.

## Import errors when using the package

Ensure `workflow_kit` is installed (editable install recommended for
development) and listed in `INSTALLED_APPS`.

## "Couldn't import Django"

Install development dependencies:

```bash
pip install -e ".[dev]"
```

Open an issue at
<https://github.com/anomalyco/django-workflow-kit/issues> if problems persist.