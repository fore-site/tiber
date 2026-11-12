from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import EngagementEvent
from ...domain.enums import DeliveryChannel, EngagementEventType
from ...domain.repositories import EngagementEventRepository
from ...infrastructure.models.engagement_event import EngagementEventModel


class SQLAlchemyEngagementEventRepository(EngagementEventRepository):
    """SQLAlchemy implementation of the EngagementEventRepository.

    Events are append-only: there is no update or delete method by design.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an async session."""
        self._session = session

    async def save(self, event: EngagementEvent) -> EngagementEvent:
        """Persist an engagement event."""
        self._session.add(self._to_model(event))
        await self._session.flush()
        return event

    async def get_by_idempotency_key(
        self, project_id: UUID, idempotency_key: str
    ) -> EngagementEvent | None:
        """Get a client-reported event by its project-scoped idempotency key."""
        model = await self._session.scalar(
            select(EngagementEventModel).where(
                EngagementEventModel.project_id == project_id,
                EngagementEventModel.idempotency_key == idempotency_key,
            )
        )
        return self._to_entity(model) if model is not None else None

    async def insert_if_absent(self, event: EngagementEvent) -> bool:
        """Insert an event unless its idempotency key is already taken.

        The conflict target is the partial unique index, so provider events
        (``idempotency_key is None``) always insert. Returns whether this call
        inserted the row; a ``False`` means the caller should read the winner.
        ``ON CONFLICT DO NOTHING`` keeps the surrounding transaction usable
        after a lost race.
        """
        statement = (
            pg_insert(EngagementEventModel)
            .values(**self._values(event))
            .on_conflict_do_nothing(
                index_elements=[
                    EngagementEventModel.project_id,
                    EngagementEventModel.idempotency_key,
                ],
                index_where=EngagementEventModel.idempotency_key.is_not(None),
            )
            .returning(EngagementEventModel.id)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none() is not None

    async def get_by_id(self, id: UUID, project_id: UUID) -> EngagementEvent | None:
        """Get an event by id within a project's scope."""
        model = await self._session.get(EngagementEventModel, id)
        if model is not None and model.project_id != project_id:
            return None
        return self._to_entity(model) if model is not None else None

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        offset: int,
        *,
        event_type: EngagementEventType | None = None,
        recipient_id: UUID | None = None,
        notification_id: UUID | None = None,
        channel: DeliveryChannel | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
    ) -> list[EngagementEvent]:
        """List a project's events, newest first, with optional filters."""
        statement = select(EngagementEventModel).where(
            EngagementEventModel.project_id == project_id
        )
        if event_type is not None:
            statement = statement.where(EngagementEventModel.event_type == event_type)
        if recipient_id is not None:
            statement = statement.where(
                EngagementEventModel.recipient_id == recipient_id
            )
        if notification_id is not None:
            statement = statement.where(
                EngagementEventModel.notification_id == notification_id
            )
        if channel is not None:
            statement = statement.where(EngagementEventModel.channel == channel)
        if occurred_after is not None:
            statement = statement.where(
                EngagementEventModel.occurred_at >= occurred_after
            )
        if occurred_before is not None:
            statement = statement.where(
                EngagementEventModel.occurred_at <= occurred_before
            )
        statement = (
            statement.order_by(
                EngagementEventModel.occurred_at.desc(),
                EngagementEventModel.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        models = (await self._session.scalars(statement)).all()
        return [self._to_entity(model) for model in models]

    async def list_by_notification(
        self, notification_id: UUID, limit: int, offset: int
    ) -> list[EngagementEvent]:
        """List all engagement events for a notification."""
        models = (
            await self._session.scalars(
                select(EngagementEventModel)
                .where(EngagementEventModel.notification_id == notification_id)
                .order_by(
                    EngagementEventModel.occurred_at.desc(),
                    EngagementEventModel.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [self._to_entity(model) for model in models]

    async def list_by_recipient(
        self, recipient_id: UUID, limit: int, offset: int
    ) -> list[EngagementEvent]:
        """List all engagement events for a recipient."""
        models = (
            await self._session.scalars(
                select(EngagementEventModel)
                .where(EngagementEventModel.recipient_id == recipient_id)
                .order_by(
                    EngagementEventModel.occurred_at.desc(),
                    EngagementEventModel.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [self._to_entity(model) for model in models]

    @staticmethod
    def _values(entity: EngagementEvent) -> dict:
        return {
            "id": entity.id,
            "notification_id": entity.notification_id,
            "project_id": entity.project_id,
            "recipient_id": entity.recipient_id,
            "event_type": entity.event_type,
            "channel": entity.channel,
            "provider": entity.provider,
            "idempotency_key": entity.idempotency_key,
            "occurred_at": entity.occurred_at,
            "event_metadata": entity.metadata,
            "is_synthetic": entity.is_synthetic,
            "created_at": entity.created_at,
        }

    @classmethod
    def _to_model(cls, entity: EngagementEvent) -> EngagementEventModel:
        return EngagementEventModel(**cls._values(entity))

    @staticmethod
    def _to_entity(model: EngagementEventModel) -> EngagementEvent:
        return EngagementEvent.reconstitute(
            id=model.id,
            notification_id=model.notification_id,
            project_id=model.project_id,
            recipient_id=model.recipient_id,
            event_type=EngagementEventType(model.event_type),
            channel=DeliveryChannel(model.channel),
            provider=model.provider,
            idempotency_key=model.idempotency_key,
            occurred_at=model.occurred_at,
            metadata=model.event_metadata,
            is_synthetic=model.is_synthetic,
            created_at=model.created_at,
        )
