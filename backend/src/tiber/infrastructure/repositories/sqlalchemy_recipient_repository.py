import re
from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import Text, literal_column, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import Recipient
from ...domain.enums import DeliveryChannel
from ...domain.exceptions import RecipientAddressTakenError
from ...domain.repositories import RecipientRepository
from ...domain.services.addresses import normalize_addresses
from ...domain.value_objects import RecipientPreferences
from ...infrastructure.models.recipient import RecipientModel

# Per-channel partial unique indexes (see the migration). A violation message
# names the index, which is how an address clash is told apart from any other
# unique violation.
_ADDRESS_INDEX_PREFIX = "uq_recipients_active_address_"

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

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #

    async def add(self, recipient: Recipient) -> Recipient:
        """Insert a new recipient.

        A unique violation on an address raises ``RecipientAddressTakenError``;
        callers re-read and reuse the recipient that won the race.
        """
        await self._write(self._to_model(recipient), upsert=False)
        return recipient

    async def save(self, recipient: Recipient) -> Recipient:
        """Insert or update the recipient with the same ID.

        Recipients are immutable entities (``update_addresses``, ``claim``,
        ``archive`` ... return a new entity with the same id), so persistence
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
                raise RecipientAddressTakenError(
                    "An address already belongs to another recipient."
                ) from exc
            raise  # any other violation (primary key, external_id) is unchanged

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #

    async def get_by_id(self, id: UUID, project_id: UUID) -> Recipient | None:
        """Get a recipient by its ID."""
        model = await self._session.get(RecipientModel, id)
        if model is not None and model.project_id != project_id:
            return None
        return self._to_entity(model) if model else None

    async def get_by_external_id(
        self, external_id: str, project_id: UUID
    ) -> Recipient | None:
        """Get a recipient by its external ID."""
        result = await self._session.execute(
            select(RecipientModel)
            .where(RecipientModel.project_id == project_id)
            .where(RecipientModel.external_id == external_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def find_by_addresses(
        self, project_id: UUID, addresses: Mapping[DeliveryChannel, str]
    ) -> list[Recipient]:
        """Return distinct, NON-ARCHIVED recipients holding any of the given pairs.

        One row-level OR over the ``(channel, address)`` pairs, so a recipient matching several of them
        still appears once. ``addresses`` must already be normalized; stored
        addresses are canonical because every write goes through ``_to_model``.
        Archived recipients (for example the absorbed side of a merge) keep their
        addresses but never match.
        """
        if not addresses:
            return []

        result = await self._session.execute(
            select(RecipientModel)
            .where(RecipientModel.project_id == project_id)
            .where(RecipientModel.archived_at.is_(None))
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
        """Get the active recipient that owns a channel address within a project."""
        found = await self.find_by_addresses(project_id, {channel: address})
        return found[0] if found else None

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

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[Recipient]:
        """List a project's recipients, newest first, with pagination."""
        result = await self._session.execute(
            select(RecipientModel)
            .where(RecipientModel.project_id == project_id)
            # Offset pagination needs a total order, or pages can repeat or skip rows.
            .order_by(RecipientModel.created_at.desc(), RecipientModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    # ------------------------------------------------------------------ #
    # Mapping
    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_model(entity: Recipient) -> RecipientModel:
        # Addresses are stored canonical (emails lower-cased and trimmed) under
        # lowercase channel keys. Matching and the unique indexes compare these
        # strings, so every write must pass through here. Note that an email read
        # back is therefore lower-case even if it was supplied in mixed case.
        # Preferences are not written: see the note in ``_to_entity``.
        return RecipientModel(
            id=entity.id,
            project_id=entity.project_id,
            external_id=entity.external_id,
            addresses={
                channel.value: address
                for channel, address in normalize_addresses(entity.addresses).items()
            },
            timezone=entity.timezone,
            language=entity.language,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            archived_at=entity.archived_at,
        )

    @staticmethod
    def _to_entity(model: RecipientModel) -> Recipient:
        # JSONB round-trips enum keys as plain strings; re-key to the enum the
        # domain entity expects, mirroring Recipient.__post_init__.
        addresses = {
            DeliveryChannel(key.lower()): value
            for key, value in model.addresses.items()
        }
        # Preferences are not persisted yet - rehydrate with the empty default
        # (fully subscribed) until the persistence pass adds the columns.
        # CONSEQUENCE: until then no opt-out is ever honored, because every
        # loaded recipient looks fully subscribed.
        return Recipient.reconstitute(
            id=model.id,
            project_id=model.project_id,
            external_id=model.external_id,
            addresses=addresses,
            preferences=RecipientPreferences(),
            timezone=model.timezone,
            language=model.language,
            created_at=model.created_at,
            updated_at=model.updated_at,
            archived_at=model.archived_at,
        )
