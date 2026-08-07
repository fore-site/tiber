from datetime import datetime
from uuid import UUID, uuid4

from tiber.application.ports.idempotency import IdempotencyGuard
from tiber.application.ports.message_publisher import MessagePublisher
from tiber.domain.entities import Notification
from tiber.domain.enums import DeliveryChannel, SendTimeBasis
from tiber.domain.exceptions import NotificationNotFoundError
from tiber.domain.repositories.notification_repository import NotificationRepository
from tiber.domain.value_objects import NotificationContent


class NotificationService:
    """Application use case for notification intake."""

    def __init__(
        self,
        idempotency_guard: IdempotencyGuard,
        repository: NotificationRepository,
        publisher: MessagePublisher,
    ) -> None:
        """Initialize the service with its ports."""
        self._idempotency = idempotency_guard
        self._repository = repository
        self._publisher = publisher

    async def create_notification(
        self,
        *,
        project_id: UUID,
        recipient_id: UUID,
        channel: str,
        idempotency_key: str,
        correlation_id: UUID,
        subject: str | None = None,
        body: str | None = None,
        template_id: UUID | None = None,
        template_variables: dict | None = None,
        scheduled_at: datetime | None = None,
    ) -> Notification:
        """Create, persist, and enqueue a notification.

        Idempotent: a repeated submission with the same ``(project, key)``
        within the TTL window returns the originally persisted notification
        instead of creating another.
        """
        # 1. Idempotency check - replay the original on a duplicate key.
        existing_id = await self._idempotency.get_existing_notification_id(
            project_id,
            idempotency_key,
        )
        if existing_id is not None:
            existing = await self._repository.get_by_id(existing_id)
            if existing is not None:
                return existing

        # 2. Build the immutable domain entity.
        notification = Notification(
            id=uuid4(),
            project_id=project_id,
            recipient_id=recipient_id,
            correlation_id=correlation_id,
            channel=DeliveryChannel(channel),
            content=NotificationContent(subject=subject, body=body),
            template_id=template_id,
            template_variables=template_variables,
            idempotency_key=idempotency_key,
            scheduled_at=scheduled_at,
            send_time_basis=(
                SendTimeBasis.EXPLICIT
                if scheduled_at is not None
                else SendTimeBasis.IMMEDIATE
            ),
        )

        # 3. Persist, then record the idempotency key, then enqueue.
        # The save() flush may raise an IntegrityError if a concurrent request
        # created the same idempotency key; that surfaces to the caller.
        await self._repository.save(notification)
        await self._idempotency.check_and_store(
            project_id,
            idempotency_key,
            notification.id,
        )
        await self._publisher.publish_notification(notification.id)

        return notification

    async def get_notification(
        self, project_id: UUID, notification_id: UUID
    ) -> Notification:
        """Get a notification scoped to a project."""
        notification = await self._repository.get_by_id(notification_id)
        if notification is None or notification.project_id != project_id:
            raise NotificationNotFoundError(str(notification_id))
        return notification

    async def list_notifications(
        self, project_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[Notification]:
        """List notifications for a project with pagination."""
        return await self._repository.list_by_project(project_id, limit, offset)
