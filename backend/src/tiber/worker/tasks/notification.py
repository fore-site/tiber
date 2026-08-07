"""Notification processing tasks."""

from __future__ import annotations

import asyncio
from uuid import UUID

from celery.utils.log import get_task_logger

from ...application.services import NotificationDeliveryProcessor
from ...core.database import AsyncSessionFactory
from ...infrastructure.providers.manager import ProviderManager
from ...infrastructure.repositories.sqlalchemy_delivery_attempt_repository import (
    SQLAlchemyDeliveryAttemptRepository,
)
from ...infrastructure.repositories.sqlalchemy_notification_repository import (
    SQLAlchemyNotificationRepository,
)
from ...infrastructure.repositories.sqlalchemy_recipient_repository import (
    SQLAlchemyRecipientRepository,
)
from ..celery_app import celery_app

logger = get_task_logger(__name__)


async def _process(notification_id: UUID) -> None:
    """Load a notification and run it through the delivery processor."""
    async with AsyncSessionFactory() as session:
        notifications = SQLAlchemyNotificationRepository(session)
        recipients = SQLAlchemyRecipientRepository(session)
        attempts = SQLAlchemyDeliveryAttemptRepository(session)

        notification = await notifications.get_by_id(notification_id)
        if notification is None:
            logger.warning("Notification %s not found; skipping", notification_id)
            return

        provider = ProviderManager().get(notification.channel)

        processor = NotificationDeliveryProcessor(
            notification_repository=notifications,
            recipient_repository=recipients,
            delivery_attempt_repository=attempts,
            provider=provider,
        )

        updated = await processor.process(notification_id)
        await session.commit()

        logger.info(
            "Notification %s -> %s",
            notification_id,
            updated.status.value,
        )


@celery_app.task(
    name="notification.process",
)
def process_notification(notification_id: str) -> None:
    """Notification Processor: dispatch a notification and track the outcome."""
    logger.info("Received notification_id=%s", notification_id)
    asyncio.run(_process(UUID(notification_id)))
