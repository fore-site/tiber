"""Port for exchanging GitHub OAuth codes for verified identities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GitHubIdentity:
    """A GitHub account and one verified email address."""

    github_id: str
    email: str


class GitHubOAuthError(RuntimeError):
    """GitHub authentication could not be completed."""


class GitHubOAuthProvider(Protocol):
    """Exchange an OAuth authorization code for a verified GitHub identity."""

    async def authenticate(
        self,
        *,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> GitHubIdentity:
        """Validate the code with GitHub and return a verified identity."""
        ...
