from uuid import UUID, uuid4

from tiber.application.ports.channel_provider import ChannelProvider, ProviderResult
from tiber.domain.entities import DeliveryAttempt, Notification
from tiber.domain.enums import DeliveryAttemptStatus, NotificationStatus
from tiber.domain.exceptions import NotificationNotFoundError
from tiber.domain.repositories.delivery_attempt_repository import (
    DeliveryAttemptRepository,
)
from tiber.domain.repositories.notification_repository import NotificationRepository
from tiber.domain.repositories.recipient_repository import RecipientRepository


class NotificationDeliveryProcessor:
    """Dispatch a notification through a provider and record the outcome.

    Worker-side use case: loads the notification, resolves the recipient's
    channel address, sends via a ``ChannelProvider``, records an immutable
    ``DeliveryAttempt``, and transitions the notification to delivered/failed.
    Re-processing a notification that is no longer PENDING is a no-op.
    """

    def __init__(
        self,
        *,
        notification_repository: NotificationRepository,
        recipient_repository: RecipientRepository,
        delivery_attempt_repository: DeliveryAttemptRepository,
        provider: ChannelProvider,
    ) -> None:
        """Initialize the processor with its ports and the chosen provider."""
        self._notifications = notification_repository
        self._recipients = recipient_repository
        self._attempts = delivery_attempt_repository
        self._provider = provider

    async def process(self, notification_id: UUID) -> Notification:
        """Deliver a notification and return its updated state."""
        notification = await self._notifications.get_by_id(notification_id)
        if notification is None:
            raise NotificationNotFoundError(str(notification_id))

        # Idempotent: a notification already past PENDING is not re-dispatched.
        if notification.status != NotificationStatus.PENDING:
            return notification

        recipient = await self._recipients.get_by_id(notification.recipient_id)
        address = (recipient.addresses if recipient else {}).get(
            notification.channel.value
        )

        if not address:
            return await self._fail(
                notification,
                error=f"no {notification.channel.value} address for recipient",
            )

        result: ProviderResult = await self._provider.send(
            recipient_address=address,
            subject=notification.content.subject,
            body=notification.content.body,
            metadata={
                "notification_id": str(notification.id),
                "correlation_id": str(notification.correlation_id),
            },
        )

        if result.success:
            return await self._succeed(
                notification,
                provider_message_id=result.provider_message_id,
            )
        return await self._fail(
            notification, error=result.error_message or "delivery failed"
        )

    async def _attempt_number(self, notification_id: UUID) -> int:
        attempts = await self._attempts.list_by_notification(notification_id)
        return len(attempts) + 1

    async def _record_attempt(
        self,
        notification: Notification,
        *,
        success: bool,
        provider_message_id: str | None,
        error: str | None,
    ) -> None:
        attempt = DeliveryAttempt(
            id=uuid4(),
            notification_id=notification.id,
            attempt_number=await self._attempt_number(notification.id),
            status=(
                DeliveryAttemptStatus.SUCCEEDED
                if success
                else DeliveryAttemptStatus.FAILED
            ),
            channel=notification.channel,
            provider=getattr(self._provider, "name", None)
            or type(self._provider).__name__,
            provider_message_id=provider_message_id,
            error=error,
        )
        await self._attempts.save(attempt)

    async def _succeed(
        self,
        notification: Notification,
        *,
        provider_message_id: str | None,
    ) -> Notification:
        await self._record_attempt(
            notification,
            success=True,
            provider_message_id=provider_message_id,
            error=None,
        )
        updated = notification.mark_delivered()
        await self._notifications.save(updated)
        return updated

    async def _fail(
        self,
        notification: Notification,
        *,
        error: str,
    ) -> Notification:
        await self._record_attempt(
            notification,
            success=False,
            provider_message_id=None,
            error=error,
        )
        updated = notification.mark_failed()
        await self._notifications.save(updated)
        return updated
