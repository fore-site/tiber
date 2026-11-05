"""Publish committed outbox messages to asynchronous workers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from tiber.application.ports.message_publisher import MessagePublisher
from tiber.application.ports.outbox_relay import (
    OutboxMessage,
    OutboxRelayRepository,
)
from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.domain.repositories import NotificationRepository

logger = logging.getLogger(__name__)


class OutboxRelayService:
    """Drain committed outbox rows and publish them with at-least-once delivery."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        outbox_repository: OutboxRelayRepository,
        notification_repository: NotificationRepository,
        publisher: MessagePublisher,
        batch_size: int = 100,
        max_attempts: int = 10,
        retry_base_seconds: int = 1,
        retry_max_seconds: int = 300,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Initialize the relay with transaction, persistence, and publishing ports."""
        self._uow = unit_of_work
        self._outbox = outbox_repository
        self._notifications = notification_repository
        self._publisher = publisher
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._clock = clock

    async def relay_available(self) -> int:
        """Publish up to the configured batch size and return successful publishes."""
        published = 0
        for _ in range(self._batch_size):
            async with self._uow:
                message = await self._outbox.claim_next(self._clock())
                if message is None:
                    return published

                try:
                    await self._publish(message)
                except Exception as exc:
                    now = self._clock()
                    attempts = message.attempts + 1
                    retry_at = (
                        None
                        if attempts >= self._max_attempts
                        else now
                        + timedelta(seconds=self._retry_delay(message.attempts))
                    )
                    await self._outbox.mark_failed(
                        message.id,
                        failed_at=now,
                        error=f"{type(exc).__name__}: {exc}",
                        next_attempt_at=retry_at,
                    )
                    logger.exception(
                        "Outbox publication failed id=%s kind=%s attempts=%s",
                        message.id,
                        message.kind,
                        attempts,
                    )
                else:
                    await self._outbox.mark_published(message.id, self._clock())
                    published += 1
        return published

    async def _publish(self, message: OutboxMessage) -> None:
        """Publish one validated row using the matching worker task."""
        if message.kind == "intake":
            await self._publisher.publish_intake(message.aggregate_id)
            return

        if message.kind == "dispatch":
            project_id = message.payload.get("project_id")
            if not isinstance(project_id, str):
                raise ValueError("Dispatch outbox payload is missing project_id")
            notification = await self._notifications.get_by_id(
                message.aggregate_id, UUID(project_id)
            )
            if notification is None:
                raise ValueError(
                    f"Dispatch notification {message.aggregate_id} no longer exists"
                )
            await self._publisher.publish_notification(notification)
            return

        raise ValueError(f"Unknown outbox kind: {message.kind!r}")

    def _retry_delay(self, previous_attempts: int) -> int:
        """Return a bounded exponential delay before retrying an outbox message."""
        return min(
            self._retry_base_seconds * (2**previous_attempts),
            self._retry_max_seconds,
        )
