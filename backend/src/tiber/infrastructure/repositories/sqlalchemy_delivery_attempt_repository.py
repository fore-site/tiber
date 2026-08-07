from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import DeliveryAttempt
from ...domain.enums import DeliveryAttemptStatus, DeliveryChannel
from ...domain.repositories.delivery_attempt_repository import (
    DeliveryAttemptRepository,
)
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

    async def list_by_notification(
        self, notification_id: UUID
    ) -> list[DeliveryAttempt]:
        """List all attempts for a notification, oldest first."""
        result = await self._session.execute(
            select(DeliveryAttemptModel)
            .where(DeliveryAttemptModel.notification_id == notification_id)
            .order_by(DeliveryAttemptModel.attempt_number)
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
            provider_message_id=entity.provider_message_id,
            error=entity.error,
            created_at=entity.created_at,
        )

    @staticmethod
    def _to_entity(model: DeliveryAttemptModel) -> DeliveryAttempt:
        return DeliveryAttempt(
            id=model.id,
            notification_id=model.notification_id,
            attempt_number=model.attempt_number,
            status=DeliveryAttemptStatus(model.status),
            channel=DeliveryChannel(model.channel),
            provider=model.provider,
            provider_message_id=model.provider_message_id,
            error=model.error,
            created_at=model.created_at,
        )
