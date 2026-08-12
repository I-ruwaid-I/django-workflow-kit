# Contributing

See the [full contribution guide](contributing-guide.md).

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