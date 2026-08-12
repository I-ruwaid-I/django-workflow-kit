# Phase 14 pre-release audit

Status: in progress. No package has been published to TestPyPI or PyPI.

## Release path

Planned path:

```text
0.4.0 -> 1.0.0rc1 -> TestPyPI -> verification -> 1.0.0 -> PyPI
```

The version remains `0.4.0` until the release-candidate commit is explicitly
approved.

## Pre-release preparation

- Public API is frozen for review in `workflow_kit.__all__`.
- `workflow_kit.view_analytics` is provisioned by migration `0007` on
  `WorkflowExecution`.
- Core runtime dependencies remain Django only.
- Implemented extras are `drf`, `docs` and `dev`; placeholder Celery and Redis
  extras were removed from metadata.
- Package metadata now declares the canonical repository URLs and includes
  package templates in the wheel.
- README and docs examples were corrected to use `WorkflowExecution` for
  approval decisions.

## Release-candidate commands

These commands are prepared for the later, explicitly approved RC step:

```powershell
$py = "C:\Users\ruwaid\Desktop\Others\django-workflow-kit\.venv\Scripts\python.exe"
Remove-Item -Recurse -Force dist, django_workflow_kit.egg-info -ErrorAction SilentlyContinue
& $py -m build
& $py -m twine check dist/*
& $py -m twine upload --repository testpypi dist/django_workflow_kit-1.0.0rc1-py3-none-any.whl dist/django_workflow_kit-1.0.0rc1.tar.gz
```

Do not rely on re-uploading an already used version or artifact.
