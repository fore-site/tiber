"""Authentication results and errors, shared by the authenticators and the API layer.

An *authenticator* answers "who is this credential?". It raises an error when the
credential is not valid. *Authorization* (may this principal touch this project?) is
decided by the caller from the principal it gets back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

# Why an API key was rejected. The API layer maps each to a message; "malformed" and
# "unknown" deliberately read the same to the client.
RejectionReason = Literal["malformed", "unknown", "revoked", "expired"]


class ApiKeyAuthenticationError(Exception):
    """The presented API key is not valid."""

    def __init__(self, reason: RejectionReason) -> None:
        """Initialize the error with the reason exposed to the API layer."""
        super().__init__(reason)
        self.reason: RejectionReason = reason


@dataclass(frozen=True)
class ApiKeyPrincipal:
    """A verified API key. It is bound to exactly one project."""

    key_id: UUID
    project_id: UUID
    key_prefix: str  # safe to log; never log the raw key


AuthMethod = Literal["api_key", "jwt"]


@dataclass(frozen=True)
class AuthContext:
    """The outcome of authenticating AND authorizing a request for one project.

    ``project_id`` is the project the caller is allowed to act on. Which of
    ``api_key_id`` / ``account_id`` is set depends on ``method``; use them for audit
    logs and for later per-key or per-account decisions.
    """

    project_id: UUID
    method: AuthMethod
    api_key_id: UUID | None = None
    account_id: UUID | None = None
