"""Celery task that drains the committed transactional outbox."""

from __future__ import annotations

from celery.utils.log import get_task_logger

from ...application.services.outbox_relay import OutboxRelayService
from ...core.config import get_settings
from ...core.database import AsyncSessionFactory
from ...infrastructure.messaging.celery_publisher import CeleryPublisher
from ...infrastructure.repositories.sqlalchemy_notification_repository import (
    SQLAlchemyNotificationRepository,
)
from ...infrastructure.repositories.sqlalchemy_outbox import SQLAlchemyOutbox
from ...infrastructure.repositories.unit_of_work import SqlAlchemyUnitOfWork
from ..async_runtime import run_async
from ..celery_app import celery_app

logger = get_task_logger(__name__)
settings = get_settings()


async def _relay() -> int:
    """Compose the relay with a fresh async session and transaction owner."""
    async with AsyncSessionFactory() as session:
        service = OutboxRelayService(
            unit_of_work=SqlAlchemyUnitOfWork(session),
            outbox_repository=SQLAlchemyOutbox(session),
            notification_repository=SQLAlchemyNotificationRepository(session),
            publisher=CeleryPublisher(),
            batch_size=settings.outbox_relay_batch_size,
            max_attempts=settings.outbox_retry_max_attempts,
            retry_base_seconds=settings.outbox_retry_base_delay_seconds,
            retry_max_seconds=settings.outbox_retry_max_delay_seconds,
        )
        return await service.relay_available()


@celery_app.task(name="outbox.relay")
def relay_outbox() -> int:
    """Publish due outbox messages to the intake and delivery worker queues."""
    published = run_async(_relay())
    if published:
        logger.info("Published %s transactional outbox messages", published)
    return published
