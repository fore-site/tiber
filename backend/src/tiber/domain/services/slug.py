import re
from typing import Final

from ..exceptions import InvalidEntityAttributeError

SLUG_RE: Final = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SLUG_TOKEN_RE: Final = re.compile(r"[a-z0-9]+")


def derive_slug(name: str) -> str:
    """Derive a URL-safe slug from a project name.

    Lowercase ASCII letters and digits are kept as tokens and joined with
    single hyphens. All other characters are treated as token separators and discarded.
    """
    return "-".join(SLUG_TOKEN_RE.findall(name.lower()))


def require_derivable_name(name: str) -> None:
    """Raise unless the name can produce a non-empty slug."""
    if not derive_slug(name):
        raise InvalidEntityAttributeError(
            "Project name must contain at least one ASCII letter or "
            f"digit for slug derivation (got: {name!r})"
        )
