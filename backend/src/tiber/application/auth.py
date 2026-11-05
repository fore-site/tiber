"""Authentication results and errors, shared by the authenticators and the API layer.

An *authenticator* answers "who is this credential?". It raises an error when the
credential is not valid. *Authorization* (may this principal touch this project?) is
decided by the caller from the principal it gets back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


@dataclass
class AuthAccount:
    """Application view of account identity and authentication state."""

    id: UUID
    email: str
    role: str
    is_verified: bool
    is_active: bool
    auth_version: int
    pending_email: str | None
    password_hash: str | None
    github_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AuthContext:
    """The outcome of authenticating AND authorizing a request for one project.

    ``project_id`` is set for API keys and ``account_id`` for dashboard JWTs.
    Use the identity fields for audit logs and rate-limit target selection.
    """

    project_id: UUID | None
    method: AuthMethod
    api_key_id: UUID | None = None
    account_id: UUID | None = None
    token_id: str | None = None
    token_expiry: int | None = None
    session_id: str | None = None
