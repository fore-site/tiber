"""Notification processing tasks."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID

from celery.utils.log import get_task_logger

from ...application.services import (
    DispatchPolicyGuard,
    NotificationDeliveryProcessor,
    NotificationTemplateResolver,
    PolicyResolver,
)
from ...core.config import get_settings
from ...core.database import AsyncSessionFactory
from ...domain.entities import Notification
from ...domain.enums import NotificationStatus
from ...domain.exceptions import (
    InvalidNotificationStateError,
    ProjectScopeViolationError,
    RecipientNotFoundError,
    TemplateChannelMismatchError,
    TemplateNotFoundError,
)
from ...events.job_payload import NotificationJobPayload
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
from ...infrastructure.repositories.sqlalchemy_template_repository import (
    SQLAlchemyTemplateRepository,
)
from ..celery_app import celery_app
from ..retry import exponential_backoff

logger = get_task_logger(__name__)

SETTINGS = get_settings()

PERMANENT_DELIVERY_ERRORS = (
    InvalidNotificationStateError,
    ProjectScopeViolationError,
    RecipientNotFoundError,
    TemplateChannelMismatchError,
    TemplateNotFoundError,
)


async def _process(notification_id: UUID) -> Notification | None:
    """Load a notification and run it through the delivery processor."""
    async with AsyncSessionFactory() as session:
        notifications = SQLAlchemyNotificationRepository(session)
        recipients = SQLAlchemyRecipientRepository(session)
        attempts = SQLAlchemyDeliveryAttemptRepository(session)
        templates = SQLAlchemyTemplateRepository(session)

        notification = await notifications.get_by_id(notification_id)
        if notification is None:
            logger.warning("Notification %s not found; skipping", notification_id)
            return None

        provider = ProviderManager().get(notification.channel)

        processor = NotificationDeliveryProcessor(
            notification_repository=notifications,
            recipient_repository=recipients,
            delivery_attempt_repository=attempts,
            provider=provider,
            # Worker-time policy re-check (permissive default preferences) and
            # template rendering with direct-content fallback.
            policy_guard=DispatchPolicyGuard(PolicyResolver()),
            template_resolver=NotificationTemplateResolver(
                template_repository=templates
            ),
        )

        updated = await processor.process(notification_id)
        await session.commit()

        logger.info(
            "Notification %s -> %s",
            notification_id,
            updated.status.value,
        )
        return updated


def _seconds_until(scheduled_at: datetime) -> int:
    """Seconds between now and ``scheduled_at`` (floored at 0)."""
    return max(0, int((scheduled_at - datetime.now(UTC)).total_seconds()))


def _should_defer(notification: Notification) -> bool:
    """Return True when the notification is not yet due and must be rescheduled."""
    if notification.status != NotificationStatus.PENDING:
        return False
    if notification.scheduled_at is None:
        return False
    return notification.scheduled_at > datetime.now(UTC)


@celery_app.task(
    name="notification.process",
    bind=True,
    max_retries=SETTINGS.notification_retry_max_attempts,
    default_retry_delay=SETTINGS.notification_retry_base_delay_seconds,
)
def process_notification(self, job) -> None:
    """Notification Processor: dispatch a notification and track the outcome.

    Accepts a structured ``NotificationJobPayload`` (or its JSON dict) and
    delivers the notification. A delivery failure that raises (transient
    broker, database, or provider error) is retried with exponential backoff up
    to the configured max attempts; once the budget is exhausted the job is not
    acked (``task_acks_late``) so RabbitMQ dead-letters it to the channel DLQ.

    The worker never delivers before ``scheduled_at``: if the notification is
    still PENDING and its scheduled time lies in the future, the job is
    re-dispatched with a countdown of the remaining delay instead of being
    delivered early. Re-dispatches are idempotent - the processor only ever
    delivers a notification that is PENDING and due.
    """
    payload = _coerce_payload(job)
    logger.info(
        "Received job notification_id=%s correlation_id=%s channel=%s",
        payload.notification_id,
        payload.correlation_id,
        payload.channel.value,
    )

    if payload.scheduled_at is not None and payload.scheduled_at > datetime.now(UTC):
        countdown = _seconds_until(payload.scheduled_at)
        celery_app.tasks["notification.process"].apply_async(
            args=[payload.to_json_dict()],
            countdown=countdown,
            routing_key=payload.routing_key,
        )
        return

    try:
        updated = asyncio.run(_process(payload.notification_id))
    except PERMANENT_DELIVERY_ERRORS as exc:
        asyncio.run(_mark_permanent_failure(payload.notification_id, str(exc)))
        return
    except Exception as exc:  # transient infra/provider error -> bounded retry
        _retry_or_dead_letter(self, payload, exc)

    if (
        updated is not None
        and updated.scheduled_at is not None
        and _should_defer(updated)
    ):
        countdown = _seconds_until(updated.scheduled_at)
        logger.info(
            "Notification %s scheduled for %s; deferring for %ss",
            payload.notification_id,
            updated.scheduled_at,
            countdown,
        )
        # Re-dispatches are idempotent and use a Celery countdown rather than
        # `self.retry` so deferral is kept distinct from failure retry/DLQ.
        celery_app.tasks["notification.process"].apply_async(
            args=[payload.to_json_dict()],
            countdown=countdown,
            routing_key=payload.routing_key,
        )


def _coerce_payload(job) -> NotificationJobPayload:
    """Normalize a JSON dict (or an already-built payload) into the contract type."""
    if isinstance(job, NotificationJobPayload):
        return job
    return NotificationJobPayload.model_validate(job)


def _retry_or_dead_letter(
    task, payload: NotificationJobPayload, exc: Exception
) -> NoReturn:
    """Re-raise with exponential backoff, or raise ``exc`` when the budget is spent.

    On ``task.retry`` we supply an exponential backoff ``countdown`` derived from
    the payload's retry state (bounded by the configured max delay). When the
    attempt ceiling is reached the original exception is (re)raised, so with
    ``task_acks_late`` the message is not acknowledged and the broker
    dead-letters the job to its channel DLQ.
    """
    max_attempts = SETTINGS.notification_retry_max_attempts
    if payload.retry.attempt >= max_attempts:
        logger.error(
            "Retry budget exhausted notification_id=%s; routing to DLQ",
            payload.notification_id,
        )
        raise exc

    countdown = exponential_backoff(
        payload.retry.attempt,
        base_delay=SETTINGS.notification_retry_base_delay_seconds,
        factor=SETTINGS.notification_retry_backoff_factor,
        max_delay=SETTINGS.notification_retry_max_delay_seconds,
    )
    logger.warning(
        "Retrying notification_id=%s attempt=%s in %ss",
        payload.notification_id,
        payload.retry.attempt + 1,
        countdown,
    )
    next_payload = payload.model_copy(update={"retry": payload.retry.next_attempt()})
    raise task.retry(
        args=[next_payload.to_json_dict()],
        exc=exc,
        countdown=countdown,
        max_retries=max_attempts,
    )


async def _mark_permanent_failure(notification_id: UUID, reason: str) -> None:
    """Persist a terminal failure for a non-retryable worker error."""
    async with AsyncSessionFactory() as session:
        repository = SQLAlchemyNotificationRepository(session)
        notification = await repository.get_by_id(notification_id)
        if notification is not None and notification.status in (
            NotificationStatus.PENDING,
            NotificationStatus.PROCESSING,
        ):
            await repository.save(notification.mark_failed())
            await session.commit()
