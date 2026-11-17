from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from ...domain.entities import SenderIdentity
from ...domain.enums import DeliveryChannel


class SenderIdentityCreateRequest(BaseModel):
    """Fields accepted when registering a project email sender."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        str_min_length=1,
    )

    from_email: EmailStr = Field(
        description="From address on the domain being registered.",
    )
    display_name: str | None = Field(
        default=None,
        max_length=100,
        description="Optional display name placed before the address.",
    )
    reply_to: EmailStr | None = Field(
        default=None,
        description="Optional Reply-To address.",
    )


class SenderIdentityResponse(BaseModel):
    """API representation of a project sender identity."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    project_id: UUID
    channel: DeliveryChannel
    provider: str
    from_email: str
    display_name: str | None
    reply_to: str | None
    domain: str
    status: str
    is_verified: bool
    dns_records: list[dict[str, Any]]
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, identity: SenderIdentity) -> SenderIdentityResponse:
        """Build the response from a domain sender identity."""
        return cls(
            id=identity.id,
            project_id=identity.project_id,
            channel=identity.channel,
            provider=identity.provider,
            from_email=identity.from_email,
            display_name=identity.display_name,
            reply_to=identity.reply_to,
            domain=identity.domain,
            status=identity.status,
            is_verified=identity.is_verified,
            dns_records=list(identity.dns_records),
            verified_at=identity.verified_at,
            created_at=identity.created_at,
            updated_at=identity.updated_at,
        )


class SenderIdentityListResponse(BaseModel):
    """All sender identities configured for a project."""

    data: list[SenderIdentityResponse]
