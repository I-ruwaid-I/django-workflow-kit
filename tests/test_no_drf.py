"""Phase 6 tests: the core package must work without Django REST Framework.

The ``workflow_kit.api`` package is an optional extra. Installing DRF is
never required for the engine itself. These tests simulate an environment
where ``rest_framework`` is unavailable and verify (a) the core package
imports cleanly and (b) importing ``workflow_kit.api`` fails only because DRF
is missing — never because the core is coupled to DRF.
"""

import subprocess
import sys

IMPORTER = r"""
import sys

class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name == "rest_framework" or name.startswith("rest_framework."):
            raise ImportError(f"No module named {name!r}")
        return None

sys.meta_path.insert(0, Blocker())
for name in list(sys.modules):
    if name == "rest_framework" or name.startswith("rest_framework."):
        del sys.modules[name]

try:
    import workflow_kit
    import workflow_kit.engine  # noqa: F401
    print("CORE_OK")
except Exception as exc:  # pragma: no cover - assertion path
    print(f"CORE_FAIL {type(exc).__name__}: {exc}")
    sys.exit(1)

try:
    import workflow_kit.api.urls  # noqa: F401
    print("API_URLS_IMPORTED")
except ImportError:
    print("API_URLS_BLOCKED")
"""


def _run_blocker() -> str:
    completed = subprocess.run(
        [sys.executable, "-c", IMPORTER],
        capture_output=True,
        text=True,
        cwd=None,
    )
    return completed.stdout.strip()


def test_core_package_imports_without_drf():
    output = _run_blocker()
    assert "CORE_OK" in output


def test_api_package_requires_drf():
    output = _run_blocker()
    assert "API_URLS_BLOCKED" in output
    assert "API_URLS_IMPORTED" not in output
