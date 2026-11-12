from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import DeliveryAttempt
from ...domain.enums import DeliveryAttemptStatus, DeliveryChannel
from ...domain.repositories import DeliveryAttemptRepository
from ...infrastructure.models.delivery_attempt import DeliveryAttemptModel


class SQLAlchemyDeliveryAttemptRepository(DeliveryAttemptRepository):
    """SQLAlchemy implementation of the DeliveryAttemptRepository."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an async session."""
        self._session = session

    async def save(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        """Persist a delivery attempt."""
        model = self._to_model(attempt)
        self._session.add(model)
        await self._session.flush()
        return attempt

    async def get_by_id(
        self, id: UUID, notification_id: UUID
    ) -> DeliveryAttempt | None:
        """Get an attempt by id, scoped to its notification."""
        model = await self._session.get(DeliveryAttemptModel, id)
        if model is not None and model.notification_id != notification_id:
            return None
        return self._to_entity(model) if model is not None else None

    async def next_attempt_number(self, notification_id: UUID) -> int:
        """Return the next 1-based attempt number for a notification."""
        current = await self._session.scalar(
            select(
                func.coalesce(func.max(DeliveryAttemptModel.attempt_number), 0)
            ).where(DeliveryAttemptModel.notification_id == notification_id)
        )
        return int(current or 0) + 1

    async def list_by_notification(
        self,
        notification_id: UUID,
        limit: int,
        *,
        cursor: int | None = None,
    ) -> list[DeliveryAttempt]:
        """List a page of attempts for a notification, oldest first."""
        statement = select(DeliveryAttemptModel).where(
            DeliveryAttemptModel.notification_id == notification_id
        )
        if cursor is not None:
            statement = statement.where(DeliveryAttemptModel.attempt_number > cursor)
        result = await self._session.execute(
            statement.order_by(DeliveryAttemptModel.attempt_number).limit(limit)
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    @staticmethod
    def _to_model(entity: DeliveryAttempt) -> DeliveryAttemptModel:
        return DeliveryAttemptModel(
            id=entity.id,
            notification_id=entity.notification_id,
            attempt_number=entity.attempt_number,
            status=entity.status,
            channel=entity.channel,
            provider=entity.provider,
            recipient_address=entity.recipient_address,
            provider_message_id=entity.provider_message_id,
            error=entity.error,
            created_at=entity.created_at,
        )

    @staticmethod
    def _to_entity(model: DeliveryAttemptModel) -> DeliveryAttempt:
        return DeliveryAttempt.reconstitute(
            id=model.id,
            notification_id=model.notification_id,
            attempt_number=model.attempt_number,
            status=DeliveryAttemptStatus(model.status),
            channel=DeliveryChannel(model.channel),
            provider=model.provider,
            recipient_address=model.recipient_address,
            provider_message_id=model.provider_message_id,
            error=model.error,
            created_at=model.created_at,
        )
