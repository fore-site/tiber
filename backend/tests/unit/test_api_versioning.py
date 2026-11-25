"""Structural guards for API versioning.

These pin the properties that make a second version cheap to add: each version
owns its document, every version is mounted side by side under its own prefix,
and no version reaches forward into a newer one.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tiber.api.versions import VERSIONS, ApiVersion

_API_DIR = Path(__file__).parents[2] / "src" / "tiber" / "api"


@pytest.fixture(scope="module")
def app() -> FastAPI:
    """Build one application for the whole module; nothing connects at import."""
    from tiber.api.main import create_app

    return create_app()


def _mounted_paths(app: FastAPI, version: ApiVersion) -> set[str]:
    paths: dict[str, Any] = app.openapi()["paths"]
    return {
        path
        for path in paths
        if path == version.prefix or path.startswith(f"{version.prefix}/")
    }


@pytest.mark.parametrize("version", VERSIONS, ids=lambda v: v.name)
def test_every_version_serves_exactly_the_paths_its_document_describes(
    app: FastAPI, version: ApiVersion
) -> None:
    """The curated document must neither invent nor omit endpoints."""
    documented = set(yaml.safe_load(version.spec_path.read_text())["paths"])
    prefixed = {
        path
        for path in documented
        if path == version.prefix or path.startswith(f"{version.prefix}/")
    }
    mounted = _mounted_paths(app, version)
    every_mounted_path = set(app.openapi()["paths"])

    # Unversioned probes such as /health are documented in the version that
    # currently serves them, so they must exist at the path they claim.
    assert documented - prefixed <= every_mounted_path, "documented but not served"
    assert not prefixed - mounted, "documented under the prefix but not served there"
    assert mounted == prefixed, "served but undocumented"


def test_version_prefixes_are_unique() -> None:
    """Two versions mounted under one prefix would shadow each other."""
    prefixes = [version.prefix for version in VERSIONS]

    assert len(prefixes) == len(set(prefixes))


def test_every_version_points_at_a_readable_document() -> None:
    """A version without its own document cannot describe a stable contract."""
    for version in VERSIONS:
        document = yaml.safe_load(version.spec_path.read_text())
        assert document["paths"], version.name
        assert document["info"]["title"], version.name


def test_no_version_imports_a_newer_one() -> None:
    """Versions may build on their predecessors, never the other way round."""
    order = {version.name: index for index, version in enumerate(VERSIONS)}

    for version in VERSIONS:
        package = _API_DIR / version.name
        for module in package.rglob("*.py"):
            text = module.read_text()
            for newer in re.findall(r"tiber\.api\.(v\d+)", text):
                assert order.get(newer, -1) <= order[version.name], (
                    f"{module} imports {newer} from {version.name}"
                )


@pytest.mark.parametrize("version", VERSIONS, ids=lambda v: v.name)
def test_docs_page_serves_its_own_version_only(
    app: FastAPI, version: ApiVersion
) -> None:
    """Each docs page reads its own document, not a combined one."""
    client = TestClient(app)

    document = client.get(f"{version.prefix}/openapi.json")
    page = client.get(f"{version.prefix}/docs")

    assert document.status_code == 200
    assert document.json() == yaml.safe_load(version.spec_path.read_text())
    assert page.status_code == 200
    assert f"{version.prefix}/openapi.json" in page.text


def test_no_unversioned_document_is_served(app: FastAPI) -> None:
    """A root document would describe every mounted version at once."""
    client = TestClient(app)

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_unversioned_probes_stay_unversioned(app: FastAPI) -> None:
    """Health and metrics must not move when the API version does."""
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/metrics").status_code == 200
