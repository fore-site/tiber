from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    """Email/password account registration payload."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    """Dashboard login credentials."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class RefreshRequest(BaseModel):
    """Opaque refresh-token rotation request."""

    refresh_token: str = Field(min_length=1)


class EmailVerificationRequest(BaseModel):
    """Email address and six-digit email verification code."""

    email: EmailStr
    otp: str = Field(pattern=r"^[0-9]{6}$")


class EmailRequest(BaseModel):
    """Email address used by resend and password-reset flows."""

    email: EmailStr


class PasswordChangeRequest(BaseModel):
    """Current and new password values."""

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class PasswordResetRequest(BaseModel):
    """Password-reset request by email."""

    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    """One-time reset token and replacement password."""

    token: str = Field(min_length=1)
    password: str = Field(min_length=8, max_length=256)


class UpdateAccountRequest(BaseModel):
    """Request a new account email address."""

    email: EmailStr


class TokenResponse(BaseModel):
    """Short-lived access token and rotating refresh token."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int


class AccountResponse(BaseModel):
    """Public dashboard account profile."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    email: EmailStr
    role: Literal["admin", "user"]
    is_verified: bool
    pending_email: EmailStr | None
    created_at: datetime
    updated_at: datetime


class RegistrationAcceptedResponse(BaseModel):
    """Registration confirmation that avoids issuing a session before verification."""

    message: str = "If the address can be registered, a verification email will arrive."


class APIKeyCreateRequest(BaseModel):
    """Project-scoped API key creation request."""

    name: str = Field(min_length=1, max_length=100)


class APIKeyResponse(BaseModel):
    """Non-secret API key metadata."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    project_id: UUID
    name: str
    prefix: str
    last_used_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None
    expires_at: datetime | None


class APIKeyWithSecretResponse(APIKeyResponse):
    """New key response; the raw key is returned only once."""

    key: str


class PaginationMeta(BaseModel):
    """Offset pagination metadata."""

    total: int
    limit: int
    offset: int


class APIKeyListResponse(BaseModel):
    """Paginated API key list."""

    data: list[APIKeyResponse]
    meta: PaginationMeta
