import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import Text, and_, delete, literal_column, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ...domain.entities import Recipient
from ...domain.enums import DeliveryChannel, NotificationCategory
from ...domain.exceptions import ConflictError
from ...domain.repositories import RecipientRepository
from ...domain.services.addresses import normalize_addresses
from ...domain.value_objects import RecipientPreferences
from ...infrastructure.models.recipient import RecipientModel

# Per-channel partial unique indexes (see the migration). A violation message
# names the index, which is how an address clash is told apart from any other
# unique violation.
_ADDRESS_INDEX_PREFIX = "uq_recipients_active_address_"
_EXTERNAL_ID_CONSTRAINT = "recipients_project_external_id_unique"

_CHANNEL_KEY_RE = re.compile(r"^[a-z_]+$")


def _address_expr(channel: DeliveryChannel):
    """Build the SQL expression for a channel's stored address (``addresses ->> 'email'``).

    The key is inlined as a literal instead of a bound parameter so the expression
    is textually identical to the one in the per-channel unique index; with a bound
    parameter the planner may not match the index. The key is an enum value, never
    user input, and is checked anyway.
    """
    key = channel.value
    if not _CHANNEL_KEY_RE.fullmatch(key):
        raise ValueError(f"Unexpected channel value: {key!r}")
    return RecipientModel.addresses.op("->>", return_type=Text)(
        literal_column(f"'{key}'")
    )


def _preferences_to_json(preferences: RecipientPreferences) -> dict[str, list[str]]:
    """Serialize consent state under stable keys.

    Quiet hours and blackout periods belong to the project's delivery
    constraints, not to the recipient, so they are not stored here.
    """
    return {
        "opted_out_channels": sorted(
            channel.value for channel in preferences.opted_out_channels
        ),
        "unsubscribed_categories": sorted(
            category.value for category in preferences.unsubscribed_categories
        ),
        "unsubscribed_topics": sorted(
            str(topic_id) for topic_id in preferences.unsubscribed_topics
        ),
    }


def _preferences_from_json(value: object) -> RecipientPreferences:
    """Rebuild consent state from the stored object (empty when absent)."""
    data = value if isinstance(value, Mapping) else {}
    return RecipientPreferences(
        opted_out_channels=frozenset(
            DeliveryChannel(str(channel))
            for channel in data.get("opted_out_channels", ())
        ),
        unsubscribed_categories=frozenset(
            NotificationCategory(str(category))
            for category in data.get("unsubscribed_categories", ())
        ),
        unsubscribed_topics=frozenset(
            UUID(str(topic_id)) for topic_id in data.get("unsubscribed_topics", ())
        ),
    )


class SQLAlchemyRecipientRepository(RecipientRepository):
    """SQLAlchemy implementation of the RecipientRepository.

    Never commits or rolls back: the unit of work owns the transaction.

    ``add`` inserts a new recipient and ``save`` upserts, so existing callers that
    use ``save`` for both keep working. Either one raises
    ``RecipientAddressTakenError`` when an address already belongs to another
    active recipient.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an async session."""
        self._session = session

    # Writes

    async def add(self, recipient: Recipient) -> Recipient:
        """Insert a new recipient.

        A unique violation on an address raises ``ConflictError``;
        callers re-read and reuse the recipient that won the race.
        """
        await self._write(self._to_model(recipient), upsert=False)
        return recipient

    async def save(self, recipient: Recipient) -> Recipient:
        """Insert or update the recipient with the same ID.

        Recipients are immutable entities (``update_addresses``, ``claim``,
        ``delete`` ... return a new entity with the same id), so persistence
        updates rather than re-inserts.
        """
        await self._write(self._to_model(recipient), upsert=True)
        return recipient

    async def _write(self, model: RecipientModel, *, upsert: bool) -> None:
        # The flush runs inside a savepoint. On Postgres a failed INSERT aborts the
        # whole transaction; rolling back only the savepoint keeps it usable, so the
        # caller can catch the error and re-read.
        try:
            async with self._session.begin_nested():
                if upsert:
                    await self._session.merge(model)
                else:
                    self._session.add(model)
                await self._session.flush()
        except IntegrityError as exc:
            if _ADDRESS_INDEX_PREFIX in str(exc.orig):
                raise ConflictError(
                    "An address already belongs to another recipient."
                ) from exc
            if _EXTERNAL_ID_CONSTRAINT in str(exc.orig):
                raise ConflictError(
                    "external_id is already used by another recipient."
                ) from exc
            raise  # any other violation (primary key) is unchanged

    # Reads

    async def get_by_id(self, id: UUID, project_id: UUID) -> Recipient | None:
        """Get a live recipient by its ID."""
        result = await self._session.execute(
            select(RecipientModel)
            .where(RecipientModel.id == id)
            .where(RecipientModel.project_id == project_id)
            .where(RecipientModel.deleted_at.is_(None))
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_external_id(
        self, external_id: str, project_id: UUID
    ) -> Recipient | None:
        """Get a live recipient by its external ID."""
        result = await self._session.execute(
            select(RecipientModel)
            .where(RecipientModel.project_id == project_id)
            .where(RecipientModel.external_id == external_id)
            .where(RecipientModel.deleted_at.is_(None))
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def find_by_addresses(
        self, project_id: UUID, addresses: Mapping[DeliveryChannel, str]
    ) -> list[Recipient]:
        """Return distinct live recipients holding any of the given pairs.

        One row-level OR over the ``(channel, address)`` pairs, so a recipient matching several of them
        still appears once. ``addresses`` must already be normalized; stored
        addresses are canonical because every write goes through ``_to_model``.
        Deleted recipients are excluded: their addresses are scrubbed, and they
        must never be matched, extended or claimed.
        """
        if not addresses:
            return []

        result = await self._session.execute(
            select(RecipientModel)
            .where(RecipientModel.project_id == project_id)
            .where(RecipientModel.deleted_at.is_(None))
            .where(
                or_(
                    *(
                        _address_expr(channel) == address
                        for channel, address in addresses.items()
                    )
                )
            )
            .order_by(RecipientModel.created_at, RecipientModel.id)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def get_by_address(
        self, project_id: UUID, channel: DeliveryChannel, address: str
    ) -> Recipient | None:
        """Get the recipient that owns a channel address within a project."""
        found = await self.find_by_addresses(project_id, {channel: address})
        return found[0] if found else None

    async def get_many_by_ids(
        self, project_id: UUID, ids: Sequence[UUID]
    ) -> list[Recipient]:
        """Load recipients by ID in one query, scoped to the project."""
        if not ids:
            return []
        result = await self._session.execute(
            select(RecipientModel)
            .where(RecipientModel.project_id == project_id)
            .where(RecipientModel.id.in_(list(ids)))
            .order_by(RecipientModel.id)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def get_many_for_update(
        self, project_id: UUID, ids: Sequence[UUID]
    ) -> list[Recipient]:
        """Lock and load recipients, ordered by id.

        Callers pass ids in the same order so two concurrent merges of overlapping
        pairs take their locks in the same order and cannot deadlock.
        """
        result = await self._session.execute(
            select(RecipientModel)
            .where(RecipientModel.project_id == project_id)
            .where(RecipientModel.id.in_(list(ids)))
            .order_by(RecipientModel.id)
            .with_for_update()
            # Refresh any copy already in the session with the state just locked.
            .execution_options(populate_existing=True)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def purge_expired(self, deleted_before: datetime, limit: int) -> int:
        """Delete one bounded batch of tombstones past their grace period.

        The ids are locked with ``SKIP LOCKED`` before the delete, following the
        project purger: a second purger running concurrently steps over the rows
        this one holds instead of blocking on them, so the two never deadlock on
        the per-row ``SET NULL`` updates the delete triggers in the history
        tables. Ordering by ``(deleted_at, id)`` keeps the lock acquisition order
        identical between runs.

        ``populate_existing`` is deliberately absent: nothing reads these rows
        back, the ids are only used as a delete key.
        """
        recipient_ids = list(
            (
                await self._session.scalars(
                    select(RecipientModel.id)
                    .where(RecipientModel.deleted_at.is_not(None))
                    .where(RecipientModel.deleted_at <= deleted_before)
                    .order_by(RecipientModel.deleted_at, RecipientModel.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        if not recipient_ids:
            return 0
        result = await self._session.execute(
            delete(RecipientModel).where(RecipientModel.id.in_(recipient_ids))
        )
        return result.rowcount or 0

    async def delete(self, recipient: Recipient) -> None:
        """Permanently delete one recipient row.

        Not the delete use case: ``RecipientManagementService.delete`` scrubs
        and hides the recipient with ``save``. Delivery history no longer blocks
        the hard delete - the recipient foreign keys are ``ON DELETE SET NULL``
        - so the ``ConflictError`` below only catches a foreign key this class
        does not know about.
        """
        model = await self._session.get(RecipientModel, recipient.id)
        if model is None or model.project_id != recipient.project_id:
            return
        try:
            async with self._session.begin_nested():
                await self._session.delete(model)
                await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError(
                "Recipient has delivery history and cannot be permanently deleted."
            ) from exc

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
        external_id: str | None = None,
    ) -> list[Recipient]:
        """List a page of a project's recipients, newest first."""
        statement = (
            select(RecipientModel)
            .where(RecipientModel.project_id == project_id)
            .where(RecipientModel.deleted_at.is_(None))
        )
        if external_id is not None:
            statement = statement.where(RecipientModel.external_id == external_id)
        if cursor is not None:
            statement = statement.where(self._before(cursor))
        result = await self._session.execute(
            statement.order_by(
                RecipientModel.created_at.desc(), RecipientModel.id.desc()
            ).limit(limit)
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    @staticmethod
    def _before(cursor: tuple[datetime, UUID]) -> ColumnElement[bool]:
        """Return the keyset predicate strictly before one ``(time, id)``."""
        created_at, recipient_id = cursor
        return or_(
            RecipientModel.created_at < created_at,
            and_(
                RecipientModel.created_at == created_at,
                RecipientModel.id < recipient_id,
            ),
        )

    # Mapping

    @staticmethod
    def _to_model(entity: Recipient) -> RecipientModel:
        # Addresses are stored canonical (emails lower-cased and trimmed) under
        # lowercase channel keys. Matching and the unique indexes compare these
        # strings, so every write must pass through here. Note that an email read
        # back is therefore lower-case even if it was supplied in mixed case.
        return RecipientModel(
            id=entity.id,
            project_id=entity.project_id,
            external_id=entity.external_id,
            addresses={
                channel.value: address
                for channel, address in normalize_addresses(entity.addresses).items()
            },
            preferences=_preferences_to_json(entity.preferences),
            timezone=entity.timezone,
            language=entity.language,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            deleted_at=entity.deleted_at,
        )

    @staticmethod
    def _to_entity(model: RecipientModel) -> Recipient:
        # JSONB round-trips enum keys as plain strings; re-key to the enum the
        # domain entity expects, mirroring Recipient.__post_init__.
        addresses = {
            DeliveryChannel(key.lower()): value
            for key, value in model.addresses.items()
        }
        return Recipient.reconstitute(
            id=model.id,
            project_id=model.project_id,
            external_id=model.external_id,
            addresses=addresses,
            preferences=_preferences_from_json(model.preferences),
            timezone=model.timezone,
            language=model.language,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )
