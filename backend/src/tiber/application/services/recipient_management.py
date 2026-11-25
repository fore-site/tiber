"""Use cases for project-scoped recipient lifecycle management."""

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from uuid import UUID

from tiber.application.pagination import (
    CursorPage,
    decode_time_id_cursor,
    encode_cursor,
)
from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.domain.entities import Recipient
from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.domain.exceptions import (
    EntityNotFoundError,
    InvalidEntityAttributeError,
)
from tiber.domain.repositories import RecipientRepository
from tiber.domain.value_objects import BlackoutPeriod, QuietHours
from tiber.domain.value_objects.preferences import UNSET, Unset

# How long a scrubbed tombstone stays addressable by id before the purge removes
# it. The window exists so history-heavy rows are not fought over immediately and
# so an accidental delete is still diagnosable; the personal data is already gone
# at delete time, so this is operational slack, not a privacy guarantee.
RECIPIENT_PURGE_GRACE_PERIOD = timedelta(days=7)


def _apply(mutation, *args) -> Recipient:
    """Run an entity mutation whose invariant violation is a client error.

    The entity raises ``ValueError`` for consent/address conflicts (for example
    dropping the address of an opted-out channel). Through the API that is a
    rejected request, not a server fault, so it is re-raised as a domain error
    with a 422 mapping.
    """
    try:
        return mutation(*args)
    except ValueError as exc:
        raise InvalidEntityAttributeError(str(exc)) from exc


class RecipientManagementService:
    """Manage recipients, including their deletion."""

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
        external_id: str,
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

    async def get_by_external_id(self, project_id: UUID, external_id: str) -> Recipient:
        """Return one recipient by the client's external identifier."""
        recipient = await self._recipients.get_by_external_id(external_id, project_id)
        if recipient is None:
            raise EntityNotFoundError(Recipient, external_id)
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
        async with self._uow:
            return await self._recipients.save(
                _apply(recipient.update_addresses, addresses)
            )

    async def update_by_external_id(
        self,
        *,
        project_id: UUID,
        external_id: str,
        addresses: dict[DeliveryChannel, str],
    ) -> Recipient:
        """Replace a recipient's address book, addressed by external ID."""
        recipient = await self.get_by_external_id(project_id, external_id)
        async with self._uow:
            return await self._recipients.save(
                _apply(recipient.update_addresses, addresses)
            )

    async def update_preferences_by_external_id(
        self,
        *,
        project_id: UUID,
        external_id: str,
        opted_out_channels: Collection[DeliveryChannel] | None = None,
        unsubscribed_categories: Collection[NotificationCategory] | None = None,
        unsubscribed_topics: Collection[UUID] | None = None,
        blackout_period: BlackoutPeriod | None | Unset = UNSET,
        quiet_hours: QuietHours | None | Unset = UNSET,
    ) -> Recipient:
        """Apply a partial delivery-preferences update by external ID.

        Omitted consent collections keep their stored value; an empty one
        clears it. For time restrictions, ``UNSET`` keeps the stored value
        while ``None`` clears it.
        """
        recipient = await self.get_by_external_id(project_id, external_id)
        try:
            preferences = recipient.preferences.merged_with(
                opted_out_channels=opted_out_channels,
                unsubscribed_categories=unsubscribed_categories,
                unsubscribed_topics=unsubscribed_topics,
                blackout_period=blackout_period,
                quiet_hours=quiet_hours,
            )
        except ValueError as exc:
            raise InvalidEntityAttributeError(str(exc)) from exc
        async with self._uow:
            return await self._recipients.save(
                _apply(recipient.update_preferences, preferences)
            )

    async def delete(
        self,
        *,
        project_id: UUID,
        recipient_id: UUID,
    ) -> Recipient:
        """Delete a recipient: hide the row and scrub its personal data.

        One write, so the marker and the scrubbing cannot diverge. The row
        itself stays because delivery history references it; a scheduled purge
        removes it later. ``get`` already ignores deleted recipients, so this
        raises ``EntityNotFoundError`` when the recipient is already deleted.
        """
        recipient = await self.get(project_id, recipient_id)
        async with self._uow:
            return await self._recipients.save(recipient.delete())

    async def delete_by_external_id(
        self,
        *,
        project_id: UUID,
        external_id: str,
    ) -> Recipient:
        """Delete a recipient, addressed by external ID."""
        recipient = await self.get_by_external_id(project_id, external_id)
        async with self._uow:
            return await self._recipients.save(recipient.delete())

    async def purge_expired(self, *, limit: int = 500) -> int:
        """Remove a batch of tombstones whose grace period has elapsed.

        The cutoff is computed here, from the same clock the API uses, rather
        than accepted as an argument: a caller that passes a timestamp could
        purge rows that are still inside the window by accident.
        """
        cutoff = datetime.now(UTC) - RECIPIENT_PURGE_GRACE_PERIOD
        async with self._uow:
            return await self._recipients.purge_expired(cutoff, limit)
