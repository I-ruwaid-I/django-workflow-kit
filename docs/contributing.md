# Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) at the repository root for the full
contribution guide.

## Testing

```bash
pip install -e ".[dev]"
pytest
```

## Formatting and linting

```bash
ruff check .
ruff format --check .
```

## Type checking

```bash
mypy workflow_kit
```