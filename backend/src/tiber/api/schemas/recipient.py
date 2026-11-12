from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ...domain.entities import Recipient
from ...domain.enums import DeliveryChannel


class RecipientResponse(BaseModel):
    """API representation of a persisted recipient."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    external_id: str | None = None
    addresses: dict[str, str]
    opted_out_channels: list[DeliveryChannel]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    @classmethod
    def from_entity(cls, recipient: Recipient) -> RecipientResponse:
        """Build the API representation from a domain recipient."""
        return cls(
            id=recipient.id,
            project_id=recipient.project_id,
            external_id=recipient.external_id,
            addresses={
                channel.value: address
                for channel, address in recipient.addresses.items()
            },
            opted_out_channels=sorted(recipient.preferences.opted_out_channels),
            created_at=recipient.created_at,
            updated_at=recipient.updated_at,
            deleted_at=recipient.deleted_at,
        )


class RecipientListResponse(BaseModel):
    """One cursor page of project recipients."""

    data: list[RecipientResponse]
    next_cursor: str | None = None
