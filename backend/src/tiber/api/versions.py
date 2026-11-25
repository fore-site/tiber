"""The API versions this service serves, and the seam between them.

A version is a bundle of routers plus the curated OpenAPI document that
describes it. `create_app` mounts every registered version under its own
prefix, so two versions coexist by construction: a client on `/v1` never sees
a change made for `/v2`.

Adding a version:

1. create `tiber.api.v2` exposing an `api_v2` bundle, including the v1
   routers whose contract did not change;
2. add it to `VERSIONS` below with its curated spec.

Nothing in `tiber.api.v1` or the domain layer moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter

from tiber.api.v1 import api_v1

_API_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ApiVersion:
    """One mounted API version and the document that describes it."""

    name: str
    router: APIRouter
    spec_path: Path
    deprecated: bool = False

    @property
    def prefix(self) -> str:
        """Path prefix every route of this version is mounted under."""
        return f"/{self.name}"


VERSIONS: tuple[ApiVersion, ...] = (
    ApiVersion(name="v1", router=api_v1, spec_path=_API_DIR / "v1" / "openapi.yaml"),
)
