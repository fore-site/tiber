"""Per-version documentation endpoints.

The app itself is created without the framework's built-in `/docs`,
`/redoc` and `/openapi.json`: a single generated document would describe
whichever versions happen to be mounted at once, which is not a contract any
client can rely on. Each version instead serves the curated document it owns,
so `/v1/docs` describes v1 and nothing else.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from tiber.api.versions import ApiVersion
from tiber.core.config import Settings


@functools.cache
def load_spec(path: str) -> dict:
    """Read a curated OpenAPI document once, from disk.

    Served as written rather than generated from the route objects: the YAML is
    the reviewed artifact clients integrate against, and the contract tests
    assert it matches the mounted routes.
    """
    return yaml.safe_load(Path(path).read_text())


def _document(version: ApiVersion) -> Callable[[], JSONResponse]:
    async def handler() -> JSONResponse:
        """Return this version's curated OpenAPI document."""
        return JSONResponse(load_spec(str(version.spec_path)))

    return handler


def _swagger_ui(version: ApiVersion, title: str) -> Callable[[], HTMLResponse]:
    async def handler() -> HTMLResponse:
        """Render Swagger UI against this version's own document."""
        return get_swagger_ui_html(
            openapi_url=f"{version.prefix}/openapi.json",
            title=title,
        )

    return handler


def _redoc(version: ApiVersion, title: str) -> Callable[[], HTMLResponse]:
    async def handler() -> HTMLResponse:
        """Render ReDoc against this version's own document."""
        return get_redoc_html(
            openapi_url=f"{version.prefix}/openapi.json",
            title=title,
        )

    return handler


def register_docs(app: FastAPI, version: ApiVersion, settings: Settings) -> None:
    """Add this version's document, Swagger UI and ReDoc under its prefix."""
    title = f"{settings.app_name} {version.name}"

    if settings.openapi_enabled:
        app.add_api_route(
            f"{version.prefix}/openapi.json",
            _document(version),
            methods=["GET"],
            include_in_schema=False,
            name=f"{version.name}_openapi_document",
        )
    if settings.docs_enabled:
        app.add_api_route(
            f"{version.prefix}/docs",
            _swagger_ui(version, title),
            methods=["GET"],
            include_in_schema=False,
            name=f"{version.name}_docs",
        )
    if settings.redoc_enabled:
        app.add_api_route(
            f"{version.prefix}/redoc",
            _redoc(version, title),
            methods=["GET"],
            include_in_schema=False,
            name=f"{version.name}_redoc",
        )
