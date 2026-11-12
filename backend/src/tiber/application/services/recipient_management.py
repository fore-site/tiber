"""Use cases for project-scoped recipient lifecycle management."""

from uuid import UUID

from tiber.application.pagination import (
    CursorPage,
    decode_time_id_cursor,
    encode_cursor,
)
from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.domain.entities import Recipient
from tiber.domain.enums import DeliveryChannel
from tiber.domain.exceptions import ConflictError, EntityNotFoundError
from tiber.domain.repositories import RecipientRepository


class RecipientManagementService:
    """Manage recipients, including their soft and permanent deletion."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        recipient_repository: RecipientRepository,
    ) -> None:
        """Bind the recipient repository and transaction boundary."""
        self._uow = unit_of_work
        self._recipients = recipient_repository

    async def create(
        self,
        *,
        project_id: UUID,
        external_id: str | None,
        addresses: dict[DeliveryChannel, str],
    ) -> Recipient:
        """Register a new recipient in a project."""
        recipient = Recipient.create(
            project_id=project_id,
            external_id=external_id,
            addresses=addresses,
        )
        async with self._uow:
            return await self._recipients.add(recipient)

    async def get(self, project_id: UUID, recipient_id: UUID) -> Recipient:
        """Return one recipient, scoped to the project."""
        recipient = await self._recipients.get_by_id(recipient_id, project_id)
        if recipient is None:
            raise EntityNotFoundError(Recipient, str(recipient_id))
        return recipient

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

    async def update(
        self,
        *,
        project_id: UUID,
        recipient_id: UUID,
        addresses: dict[DeliveryChannel, str],
    ) -> Recipient:
        """Replace a recipient's address book."""
        recipient = await self.get(project_id, recipient_id)
        if recipient.deleted_at is not None:
            raise EntityNotFoundError(Recipient, str(recipient_id))
        async with self._uow:
            return await self._recipients.save(recipient.update_addresses(addresses))

    async def delete(
        self,
        *,
        project_id: UUID,
        recipient_id: UUID,
        permanent: bool = False,
    ) -> Recipient:
        """Soft-delete a recipient, or purge an already deleted one.

        Permanent deletion requires a prior soft delete and is rejected with a
        conflict when delivery history still references the recipient.
        """
        recipient = await self.get(project_id, recipient_id)
        if recipient.deleted_at is not None:
            if not permanent:
                return recipient
            async with self._uow:
                await self._recipients.delete(recipient)
            return recipient
        if permanent:
            raise ConflictError(
                "Recipient must be deleted before it can be permanently removed."
            )
        async with self._uow:
            return await self._recipients.save(recipient.delete())
