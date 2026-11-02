from __future__ import annotations

from pathlib import Path

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply suite markers based on the test directory."""
    test_root = Path(__file__).parent
    for item in items:
        suite = item.path.relative_to(test_root).parts[0]
        if suite in {"unit", "integration", "e2e"}:
            item.add_marker(getattr(pytest.mark, suite))
