# Configuration

All package settings live in the `WORKFLOW_KIT` dict in your Django settings
module.

```python
WORKFLOW_KIT = {
    "ATOMIC_TRANSITIONS": True,
}
```

Available options:

| Option | Default | Description |
| ------ | ------- | ----------- |
| `ATOMIC_TRANSITIONS` | `True` | Wrap each transition in a database transaction. |

Defaults mean basic usage requires no configuration.