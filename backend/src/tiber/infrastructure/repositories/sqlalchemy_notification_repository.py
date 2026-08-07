from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities.notification import Notification
from ...domain.enums import DeliveryChannel, NotificationStatus, SendTimeBasis
from ...domain.repositories.notification_repository import NotificationRepository
from ...domain.value_objects import NotificationContent
from ...infrastructure.models.notification import NotificationModel


class SQLAlchemyNotificationRepository(NotificationRepository):
    """SQLAlchemy implementation of the NotificationRepository."""

    def __init__(self, session: AsyncSession):
        """SQLAlchemy implementation of the NotificationRepository."""
        self._session = session

    async def save(self, notification: Notification) -> Notification:
        """Persist a notification."""
        model = self._to_model(notification)
        self._session.add(model)
        await self._session.flush()
        return notification

    async def get_by_id(self, id: UUID) -> Notification | None:
        """Get a notification by its ID."""
        model = await self._session.get(NotificationModel, id)
        return self._to_entity(model) if model else None

    async def get_by_idempotency_key(
        self, project_id: UUID, key: str
    ) -> Notification | None:
        """Get a notification by its idempotency key."""
        result = await self._session.execute(
            select(NotificationModel)
            .where(NotificationModel.project_id == project_id)
            .where(NotificationModel.idempotency_key == key)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[Notification]:
        """List all notifications for a project with pagination."""
        result = await self._session.execute(
            select(NotificationModel)
            .where(NotificationModel.project_id == project_id)
            .limit(limit)
            .offset(offset)
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    @staticmethod
    def _to_model(entity: Notification) -> NotificationModel:
        # NOTE: JSONB columns must not be passed an explicit Python None - the
        # asyncpg driver serializes None as JSON "null" rather than SQL NULL,
        # which would trip the IS NULL / jsonb_typeof checks. Only include
        # template_variables when it actually has a value.
        fields: dict = {
            "id": entity.id,
            "project_id": entity.project_id,
            "recipient_id": entity.recipient_id,
            "template_id": entity.template_id,
            "correlation_id": entity.correlation_id,
            "channel": entity.channel,
            "status": entity.status,
            "idempotency_key": entity.idempotency_key,
            "subject": entity.content.subject,
            "body": entity.content.body,
            "scheduled_at": entity.scheduled_at,
            "send_time_basis": entity.send_time_basis,
            "policy_violation_reason": entity.policy_violation_reason,
            "delivered_at": entity.delivered_at,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }
        if entity.template_variables is not None:
            fields["template_variables"] = entity.template_variables
        return NotificationModel(**fields)

    @staticmethod
    def _to_entity(model: NotificationModel) -> Notification:
        return Notification(
            id=model.id,
            project_id=model.project_id,
            recipient_id=model.recipient_id,
            correlation_id=model.correlation_id,
            template_id=model.template_id,
            template_variables=model.template_variables,
            created_at=model.created_at,
            updated_at=model.updated_at,
            send_time_basis=SendTimeBasis(model.send_time_basis),
            channel=DeliveryChannel(model.channel),
            content=NotificationContent(
                subject=model.subject,
                body=model.body,
            ),
            status=NotificationStatus(model.status),
            scheduled_at=model.scheduled_at,
            delivered_at=model.delivered_at,
            policy_violation_reason=model.policy_violation_reason,
            idempotency_key=model.idempotency_key,
        )
