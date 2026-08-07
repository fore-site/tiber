"""...docstring placeholder..."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
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

if TYPE_CHECKING:
    from .policy import DispatchPolicyGuard
    from .template import NotificationTemplateResolver


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
        policy_guard: DispatchPolicyGuard | None = None,
        template_resolver: NotificationTemplateResolver | None = None,
    ) -> None:
        """Initialize the processor with its ports and the chosen provider.

        ``policy_guard`` and ``template_resolver`` are optional. When supplied
        the processor performs a worker-time policy re-check (marking the
        notification ``policy_rejected`` on violation, with no delivery attempt
        recorded) and resolves/renders template content before dispatch. When
        omitted the processor behaves exactly as before (no re-check, direct
        content only).
        """
        self._notifications = notification_repository
        self._recipients = recipient_repository
        self._attempts = delivery_attempt_repository
        self._provider = provider
        self._policy_guard = policy_guard
        self._template_resolver = template_resolver

    async def process(self, notification_id: UUID) -> Notification:
        """Deliver a notification and return its updated state.

        Scheduling guard: a PENDING notification whose ``scheduled_at`` is in
        the future is *not* delivered early. It is returned unchanged (still
        PENDING, no attempt recorded) so the caller can defer the job - e.g.
        requeue with a countdown - and still preserve idempotency. Once due,
        the notification is moved to PROCESSING for the duration of the send,
        then to a terminal state.
        """
        notification = await self._notifications.get_by_id(notification_id)
        if notification is None:
            raise NotificationNotFoundError(str(notification_id))

        # Idempotent: a notification already past PENDING (PROCESSING,
        # delivered, failed, ...) is not re-dispatched.
        if notification.status != NotificationStatus.PENDING:
            return notification

        # Scheduling guard - never deliver before scheduled_at.
        now = datetime.now(UTC)
        if notification.scheduled_at is not None and notification.scheduled_at > now:
            return notification

        recipient = await self._recipients.get_by_id(notification.recipient_id)

        if recipient is not None and recipient.project_id != notification.project_id:
            return await self._fail(
                notification,
                error="recipient does not belong to notification project",
            )

        # Worker-time policy re-check while still PENDING. A violation is a
        # terminal policy rejection (with a reason and no delivery attempt
        # recorded), not a delivery failure.
        if self._policy_guard is not None:
            decision = await self._policy_guard.check(notification, recipient)
            if not decision.allowed:
                updated = notification.mark_policy_rejected(
                    decision.reason or "policy violation"
                )
                await self._notifications.save(updated)
                return updated

        # Resolve content while still PENDING: render the template when one is
        # referenced, else fall back to the notification's direct content.
        if self._template_resolver is not None:
            content = await self._template_resolver.resolve_content(notification)
        else:
            content = notification.content

        # Store the rendered content in the immutable processing snapshot so
        # subsequent reads and API responses reflect exactly what was sent.
        if self._template_resolver is not None and notification.template_id is not None:
            notification = notification.with_content(content)

        # Acquire the notification for the in-flight window so a concurrent or
        # duplicate dispatch of the same id no longer sees PENDING.
        processing = notification.mark_processing()
        await self._notifications.save(processing)

        address = (recipient.addresses if recipient else {}).get(
            notification.channel.value
        )

        if not address:
            return await self._fail(
                processing,
                error=f"no {notification.channel.value} address for recipient",
            )

        result: ProviderResult = await self._provider.send(
            recipient_address=address,
            subject=content.subject,
            body=content.body,
            metadata={
                "notification_id": str(notification.id),
                "correlation_id": str(notification.correlation_id),
            },
        )

        if result.success:
            return await self._succeed(
                processing,
                provider_message_id=result.provider_message_id,
            )
        return await self._fail(
            processing, error=result.error_message or "delivery failed"
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
