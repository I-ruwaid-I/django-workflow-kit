#!/usr/bin/env python
"""Django's command-line utility for the test project."""

import os
import sys


def main() -> None:
    """Run administration tasks against the test project."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.test_project.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Couldn't import Django. Is it installed and available on PYTHONPATH?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
