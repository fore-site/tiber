"""Read side of registered recipients."""

from uuid import UUID

from tiber.application.pagination import (
    CursorPage,
    decode_time_id_cursor,
    encode_cursor,
)
from tiber.domain.entities import Recipient
from tiber.domain.repositories import RecipientRepository


class RecipientQueryService:
    """Project-scoped reads of registered recipients."""

    def __init__(self, *, recipient_repository: RecipientRepository) -> None:
        """Bind the read-side repository."""
        self._recipients = recipient_repository

    async def list(
        self,
        project_id: UUID,
        *,
        limit: int = 50,
        cursor: str | None = None,
        external_id: str | None = None,
    ) -> CursorPage[Recipient]:
        """List one page of a project's recipients, newest first."""
        after = decode_time_id_cursor(cursor, time_field="created_at")
        recipients = await self._recipients.list_by_project(
            project_id, limit + 1, cursor=after, external_id=external_id
        )
        items = recipients[:limit]
        next_cursor = (
            encode_cursor(
                created_at=items[-1].created_at.isoformat(),
                id=items[-1].id,
            )
            if len(recipients) > limit
            else None
        )
        return CursorPage(items=items, next_cursor=next_cursor)
