# Contributing

Thanks for taking the time to contribute to Django Workflow Kit.

## Development setup

Requirements: Python >= 3.12 and Git.

```bash
git clone https://github.com/anomalyco/django-workflow-kit.git
cd django-workflow-kit
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Running tests

```bash
pytest
```

Run tests with coverage:

```bash
coverage run -m pytest
coverage report
```

The CI target is 90%+ coverage on `workflow_kit`.

## Formatting and linting

```bash
ruff check .
ruff format --check .
```

Format code automatically:

```bash
ruff format .
```

## Type checking

```bash
mypy workflow_kit
```

## Pre-commit

Install the hooks before your first commit:

```bash
pre-commit install
```

## Creating a feature or a fix

1. Create a branch (`feat/...`, `fix/...`).
2. Implement the change with tests covering the new behaviour.
3. Update documentation alongside the implementation.
4. Run the full test suite and linters.
5. Open a pull request.

## Pull request expectations

- Focused scope: one feature or fix per PR.
- Every functional change includes tests that verify behaviour.
- Tests must pass and new failures on maintained code.
- Public API additions must include docstrings.
- Conventional commit-style messages (e.g. `feat:`, `fix:`, `docs:`,
  `test:`, `refactor:`).

## Things to avoid

- New dependencies without a justification.
- `print(...)` in library code — use Python's `logging` module.
- `eval()` or arbitrary execution of user/stored input.
- Modifying audit-history records after they are written.