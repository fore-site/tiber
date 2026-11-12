"""Dispatch client-registered webhook callbacks for terminal notifications.

Separation of concerns that matters operationally:

* The delivery record is written *before* this task runs, so a webhook failure
  never changes whether the notification counts as delivered.
* This task has its own retry budget and dead-letter queue, so a client endpoint
  that is down cannot consume the notification delivery retry budget.

The signature scheme is timestamped HMAC-SHA256 over ``<timestamp>.<body>``.
Including the timestamp inside the signed string is what lets a client reject
replays; this service does not deduplicate retries, so a client may receive the
same event more than once and should treat the delivery id as at-least-once.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
from celery.utils.log import get_task_logger

from ...core.config import get_settings
from ...core.database import AsyncSessionFactory
from ...core.encryption import decrypt_secret
from ...domain.enums import NotificationStatus, WebhookEventType
from ...domain.repositories import NotificationRepository, WebhookEndpointRepository
from ...infrastructure.repositories.sqlalchemy_notification_repository import (
    SQLAlchemyNotificationRepository,
)
from ...infrastructure.repositories.sqlalchemy_webhook_endpoint_repository import (
    SQLAlchemyWebhookEndpointRepository,
)
from ...infrastructure.repositories.unit_of_work import SqlAlchemyUnitOfWork
from ..async_runtime import run_async
from ..celery_app import celery_app
from ..retry import exponential_backoff

logger = get_task_logger(__name__)

SETTINGS = get_settings()

_STATUS_EVENTS: dict[NotificationStatus, WebhookEventType] = {
    NotificationStatus.DELIVERED: WebhookEventType.NOTIFICATION_DELIVERED,
    NotificationStatus.FAILED: WebhookEventType.NOTIFICATION_FAILED,
    NotificationStatus.BOUNCED: WebhookEventType.NOTIFICATION_BOUNCED,
    NotificationStatus.SUPPRESSED: WebhookEventType.NOTIFICATION_SUPPRESSED,
    NotificationStatus.CANCELLED: WebhookEventType.NOTIFICATION_CANCELLED,
}


class WebhookDispatchError(RuntimeError):
    """One or more client endpoints did not accept the callback."""


def sign_payload(secret: str, timestamp: int, payload: str) -> str:
    """Return the hex HMAC-SHA256 of ``<timestamp>.<payload>``.

    Public so the signature format can be pinned in tests and documented.
    """
    signed = f"{timestamp}.{payload}".encode()
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def _event_payload(notification, event_type: WebhookEventType) -> str:
    """Serialize one lifecycle event; stable ordering keeps signatures repeatable."""
    return json.dumps(
        {
            "id": str(uuid4()),
            "event": event_type.value,
            "created_at": datetime.now(UTC).isoformat(),
            "data": {
                "notification_id": str(notification.id),
                "transaction_id": str(notification.transaction_id),
                "project_id": str(notification.project_id),
                "channel": notification.channel.value,
                "status": notification.status.value,
                "delivered_at": (
                    notification.delivered_at.isoformat()
                    if notification.delivered_at is not None
                    else None
                ),
                "failure_reason": notification.failure_reason,
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )


async def _post_one(
    client: httpx.AsyncClient,
    *,
    endpoint,
    event_type: WebhookEventType,
    payload: str,
) -> bool:
    """POST one callback, returning False (and logging) on any failure."""
    timestamp = int(time.time())
    try:
        secret = decrypt_secret(endpoint.encrypted_signing_secret)
    except RuntimeError:
        logger.exception(
            "Cannot sign webhook callback webhook_id=%s; skipping", endpoint.id
        )
        return False

    signature = sign_payload(secret, timestamp, payload)
    try:
        response = await client.post(
            endpoint.url,
            content=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Tiber-Webhooks/1.0",
                "X-Tiber-Event": event_type.value,
                "X-Tiber-Delivery": str(uuid4()),
                "X-Tiber-Signature": f"t={timestamp},v1={signature}",
            },
        )
    except httpx.HTTPError:
        logger.warning(
            "Webhook callback failed webhook_id=%s url=%s", endpoint.id, endpoint.url
        )
        return False

    if response.is_error:
        logger.warning(
            "Webhook endpoint rejected callback webhook_id=%s status=%s",
            endpoint.id,
            response.status_code,
        )
        return False

    logger.info(
        "Webhook callback delivered webhook_id=%s event=%s",
        endpoint.id,
        event_type.value,
    )
    return True


async def _dispatch(notification_id: UUID, project_id: UUID) -> int:
    """Fan a notification's terminal state out to subscribed endpoints."""
    async with AsyncSessionFactory() as session:
        notifications: NotificationRepository = SQLAlchemyNotificationRepository(
            session
        )
        endpoints: WebhookEndpointRepository = SQLAlchemyWebhookEndpointRepository(
            session
        )
        async with SqlAlchemyUnitOfWork(session):
            notification = await notifications.get_by_id(notification_id, project_id)

        if notification is None:
            logger.warning(
                "Notification %s not found; no webhooks fired", notification_id
            )
            return 0

        event_type = _STATUS_EVENTS.get(notification.status)
        if event_type is None:
            logger.info(
                "Notification %s state=%s is not terminal; no webhooks",
                notification_id,
                notification.status.value,
            )
            return 0

        subscribed = await endpoints.list_by_event(
            project_id,
            event_type,
            limit=SETTINGS.webhook_dispatch_max_endpoints,
            cursor=None,
        )
        if not subscribed:
            return 0

        payload = _event_payload(notification, event_type)
        failures = 0
        async with httpx.AsyncClient(
            timeout=SETTINGS.webhook_endpoint_timeout_seconds
        ) as client:
            for endpoint in subscribed:
                accepted = await _post_one(
                    client,
                    endpoint=endpoint,
                    event_type=event_type,
                    payload=payload,
                )
                if not accepted:
                    failures += 1

    if failures:
        raise WebhookDispatchError(
            f"{failures} webhook endpoint(s) rejected event {event_type.value} "
            f"for notification {notification_id}"
        )
    return len(subscribed)


@celery_app.task(
    name="notification.webhook",
    bind=True,
    max_retries=SETTINGS.webhook_retry_max_attempts,
    default_retry_delay=SETTINGS.webhook_retry_base_delay_seconds,
)
def dispatch_notification_webhooks(self, notification_id: str, project_id: str) -> None:
    """Deliver lifecycle callbacks for one terminal notification.

    A retry repeats the whole fan-out, so an endpoint that already accepted the
    callback can receive it again. That is why delivery is at-least-once and
    clients should deduplicate on the payload ``id``.
    """
    try:
        run_async(_dispatch(UUID(notification_id), UUID(project_id)))
    except Exception as exc:
        if self.request.retries >= SETTINGS.webhook_retry_max_attempts:
            logger.error(
                "Webhook retry budget exhausted notification_id=%s; routing to DLQ",
                notification_id,
            )
            raise
        countdown = exponential_backoff(
            self.request.retries,
            base_delay=SETTINGS.webhook_retry_base_delay_seconds,
            factor=SETTINGS.webhook_retry_backoff_factor,
            max_delay=SETTINGS.webhook_retry_max_delay_seconds,
        )
        logger.warning(
            "Retrying webhooks notification_id=%s attempt=%s in %ss",
            notification_id,
            self.request.retries + 1,
            countdown,
        )
        raise self.retry(exc=exc, countdown=countdown) from exc
