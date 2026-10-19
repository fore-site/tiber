from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities.notification import Notification
from ...domain.enums import (
    DeliveryChannel,
    NotificationCategory,
    NotificationStatus,
    SendTimeBasis,
)
from ...domain.repositories import NotificationRepository
from ...domain.value_objects import ContentAction, ContentImage, NotificationContent
from ...infrastructure.models.notification import NotificationModel


class SQLAlchemyNotificationRepository(NotificationRepository):
    """SQLAlchemy implementation of the NotificationRepository.

    Never commits or rolls back: the unit of work owns the transaction.
    """

    def __init__(self, session: AsyncSession):
        """SQLAlchemy implementation of the NotificationRepository."""
        self._session = session

    async def save(self, notification: Notification) -> Notification:
        """Insert a notification, or update the row with the same ID.

        Notifications are immutable domain entities; state transitions
        (delivered/failed/... ) produce a *new* entity with the same id, so
        persistence must update rather than re-insert.
        """
        model = self._to_model(notification)
        await self._session.merge(model)
        await self._session.flush()
        return notification

    async def get_by_id(self, id: UUID, project_id: UUID) -> Notification | None:
        """Get a notification by its ID within a project's scope."""
        model = await self._session.get(NotificationModel, id)
        if model is not None and model.project_id != project_id:
            return None
        return self._to_entity(model) if model else None

    async def get_by_idempotency_key(
        self, project_id: UUID, key: str
    ) -> Notification | None:
        """Return the first notification stored under an idempotency key.

        Legacy: one request now creates a notification per channel, all sharing
        the key, so a key no longer identifies a single row. Idempotency is owned
        by the intake (``NotificationIntakeRepository``); delete this method once
        nothing calls it.
        """
        result = await self._session.execute(
            select(NotificationModel)
            .where(NotificationModel.project_id == project_id)
            .where(NotificationModel.idempotency_key == key)
            .order_by(NotificationModel.created_at, NotificationModel.id)
            .limit(1)
        )
        model = result.scalars().first()
        return self._to_entity(model) if model else None

    async def list_by_project(
        self, project_id: UUID, limit: int, offset: int
    ) -> list[Notification]:
        """List a project's notifications, newest first, with pagination."""
        result = await self._session.execute(
            select(NotificationModel)
            .where(NotificationModel.project_id == project_id)
            # Offset pagination needs a total order, or pages can repeat or skip rows.
            .order_by(NotificationModel.created_at.desc(), NotificationModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def list_by_correlation_id(
        self, correlation_id: UUID, project_id: UUID
    ) -> list[Notification]:
        """All notifications created by one request, oldest first."""
        result = await self._session.execute(
            select(NotificationModel)
            .where(NotificationModel.project_id == project_id)
            .where(NotificationModel.correlation_id == correlation_id)
            .order_by(NotificationModel.created_at, NotificationModel.id)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def reassign_recipient(
        self,
        *,
        project_id: UUID,
        from_recipient_id: UUID,
        to_recipient_id: UUID,
    ) -> int:
        """Repoint every notification of one recipient to another (recipient merge).

        Returns the number of rows moved.
        """
        result = await self._session.execute(
            update(NotificationModel)
            .where(NotificationModel.project_id == project_id)
            .where(NotificationModel.recipient_id == from_recipient_id)
            .values(recipient_id=to_recipient_id)
        )
        return cast(CursorResult, result).rowcount or 0

    @staticmethod
    def _to_model(entity: Notification) -> NotificationModel:
        content = entity.content
        if content is None:
            # The body column is NOT NULL, and a placeholder must never be stored.
            raise ValueError("Cannot persist a notification without content")

        # NOTE: JSONB columns must not be passed an explicit Python None - the
        # asyncpg driver serializes None as JSON "null" rather than SQL NULL,
        # which would trip the IS NULL / jsonb_typeof checks. Only include
        # template_variables when it actually has a value. ``actions`` and
        # ``images`` are NOT NULL and always carry a list.
        fields: dict = {
            "id": entity.id,
            "project_id": entity.project_id,
            "recipient_id": entity.recipient_id,
            "template_id": entity.template_id,
            "topic_id": entity.topic_id,
            "correlation_id": entity.correlation_id,
            "channel": entity.channel,
            "category": entity.category,
            "status": entity.status,
            "idempotency_key": entity.idempotency_key,
            "group_key": entity.group_key,
            "subject": content.title,
            "body": content.body,
            "actions": [{"label": a.label, "url": a.url} for a in content.actions],
            "images": [{"url": i.url, "alt": i.alt} for i in content.images],
            "send_at": entity.send_at,
            "send_time_basis": entity.send_time_basis,
            "suppression_reason": entity.suppression_reason,
            "cancellation_reason": entity.cancellation_reason,
            "failure_reason": entity.failure_reason,
            "delivered_at": entity.delivered_at,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }
        if entity.template_variables is not None:
            fields["template_variables"] = entity.template_variables
        return NotificationModel(**fields)

    @staticmethod
    def _to_entity(model: NotificationModel) -> Notification:
        return Notification.reconstitute(
            id=model.id,
            project_id=model.project_id,
            recipient_id=model.recipient_id,
            correlation_id=model.correlation_id,
            topic_id=model.topic_id,
            template_id=model.template_id,
            template_variables=model.template_variables,
            created_at=model.created_at,
            updated_at=model.updated_at,
            channel=DeliveryChannel(model.channel),
            category=NotificationCategory(model.category),
            content=NotificationContent(
                title=model.subject,
                body=model.body,
                actions=tuple(
                    ContentAction(label=a["label"], url=a["url"])
                    for a in (model.actions or [])
                ),
                images=tuple(
                    ContentImage(url=i["url"], alt=i.get("alt"))
                    for i in (model.images or [])
                ),
            ),
            status=NotificationStatus(model.status),
            send_at=model.send_at,
            # Loaded as a plain str; the entity compares members with ``is``.
            send_time_basis=SendTimeBasis(model.send_time_basis),
            delivered_at=model.delivered_at,
            suppression_reason=model.suppression_reason,
            cancellation_reason=model.cancellation_reason,
            failure_reason=model.failure_reason,
            idempotency_key=model.idempotency_key,
            group_key=model.group_key,
        )
