"""...docstring placeholder..."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from tiber.application.ports.channel_provider import ChannelProvider, ProviderResult
from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.domain.entities import DeliveryAttempt, Notification, Recipient
from tiber.domain.enums import (
    DeliveryAttemptStatus,
    DeliveryChannel,
    NotificationStatus,
    PolicyConsequence,
)
from tiber.domain.exceptions import EntityNotFoundError
from tiber.domain.repositories import (
    DeliveryAttemptRepository,
    DeliveryConstraintRepository,
    NotificationRepository,
    RecipientRepository,
)

if TYPE_CHECKING:
    from .policy import DeliveryPolicyGuard
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
        unit_of_work: UnitOfWork,
        notification_repository: NotificationRepository,
        recipient_repository: RecipientRepository,
        delivery_attempt_repository: DeliveryAttemptRepository,
        provider: ChannelProvider,
        policy_guard: DeliveryPolicyGuard | None = None,
        template_resolver: NotificationTemplateResolver | None = None,
        constraint_repository: DeliveryConstraintRepository | None = None,
        processing_lease_seconds: int = 300,
    ) -> None:
        """Initialize the processor with its ports and the chosen provider.

        ``policy_guard`` and ``template_resolver`` are optional. When supplied
        the processor performs a worker-time policy re-check: a quiet-hours
        violation postpones the notification to after the window (the worker
        re-queues it on the resume time), any other violation suppresses it
        with a reason - in both cases with no delivery attempt recorded.
        When omitted the processor behaves exactly as before (no re-check,
        direct content only). ``constraint_repository`` is optional and only
        consulted when the guard is present; without it the re-check runs
        against the recipient alone (project-level constraints unseen).
        """
        self._notifications = notification_repository
        self._uow = unit_of_work
        self._recipients = recipient_repository
        self._attempts = delivery_attempt_repository
        self._provider = provider
        self._policy_guard = policy_guard
        self._template_resolver = template_resolver
        self._constraints = constraint_repository
        self._processing_lease = timedelta(seconds=processing_lease_seconds)

    async def process(self, notification_id: UUID, *, project_id: UUID) -> Notification:
        """Deliver a notification and return its updated state.

        The lookup is project-scoped: a notification outside ``project_id``
        reads as not-found.

        Scheduling guard: a PENDING notification whose ``send_at`` is in
        the future is *not* delivered early. It is returned unchanged (still
        PENDING, no attempt recorded) so the caller can defer the job - e.g.
        requeue with a countdown - and still preserve idempotency. Once due,
        the notification is moved to PROCESSING for the duration of the send,
        then to a terminal state.
        """
        async with self._uow:
            notification = await self._notifications.get_by_id(
                notification_id, project_id
            )
            if notification is None:
                raise EntityNotFoundError(Notification, str(notification_id))

            expected_status = notification.status
            now = datetime.now(UTC)

            stale_before: datetime | None = None
            if notification.status is NotificationStatus.PROCESSING:
                stale_before = now - self._processing_lease
                if notification.updated_at > stale_before:
                    return notification
            elif notification.status is NotificationStatus.POSTPONED:
                if notification.send_at is None or notification.send_at > now:
                    return notification
                notification = notification.resume()
            elif notification.status is not NotificationStatus.PENDING:
                return notification

            if notification.send_at is not None and notification.send_at > now:
                return notification

            recipient = await self._recipients.get_by_id(
                notification.recipient_id, notification.project_id
            )
            if recipient is None:
                raise EntityNotFoundError(Recipient, str(notification.recipient_id))

            if self._policy_guard is not None:
                constraint = (
                    await self._constraints.load_constraint(notification.project_id)
                    if self._constraints is not None
                    else None
                )
                decision = await self._policy_guard.check(
                    notification, recipient, constraint
                )
                if not decision.allowed:
                    if decision.consequence is PolicyConsequence.POSTPONE:
                        if decision.resume_at is None:
                            raise ValueError(
                                "policy returned POSTPONE without a resume time"
                            )
                        updated = notification.mark_postponed(decision.resume_at)
                    else:
                        updated = notification.mark_suppressed(
                            decision.reason or "policy violation"
                        )
                    await self._notifications.save(updated)
                    return updated

            rendered = (
                await self._template_resolver.resolve(notification)
                if self._template_resolver is not None
                else None
            )
            content = rendered.content if rendered is not None else notification.content
            if (
                self._template_resolver is not None
                and notification.template_id is not None
            ):
                notification = notification.with_content(content)

            processing = (
                notification.reclaim_processing()
                if expected_status is NotificationStatus.PROCESSING
                else notification.mark_processing()
            )
            claimed = await self._notifications.claim_for_delivery(
                processing,
                expected_status=expected_status,
                stale_before=stale_before,
            )
            if not claimed:
                current = await self._notifications.get_by_id(
                    notification_id, project_id
                )
                return current or notification

            address = recipient.addresses.get(notification.channel)

        if not address:
            return await self._fail(
                processing,
                error=f"no {notification.channel.value} address for recipient",
            )

        try:
            result: ProviderResult = await self._provider.send(
                recipient_address=address,
                title=content.title,
                body=content.plain_text_body or "",
                actions=content.actions,
                images=content.images,
                html_body=(
                    content.html_body
                    if notification.channel
                    in (DeliveryChannel.EMAIL, DeliveryChannel.IN_APP)
                    else None
                ),
                metadata={
                    "notification_id": str(notification.id),
                    "transaction_id": str(notification.transaction_id),
                },
            )
        except Exception as exc:
            await self._retry(processing, error=str(exc), recipient_address=address)
            raise

        if result.success:
            return await self._succeed(
                processing,
                provider_message_id=result.provider_message_id,
                recipient_address=address,
            )
        return await self._fail(
            processing,
            error=result.error_message or "delivery failed",
            recipient_address=address,
        )

    async def _record_attempt(
        self,
        notification: Notification,
        *,
        success: bool,
        provider_message_id: str | None,
        error: str | None,
        recipient_address: str | None,
    ) -> None:
        attempt = DeliveryAttempt.create(
            notification_id=notification.id,
            status=(
                DeliveryAttemptStatus.SUCCESS if success else DeliveryAttemptStatus.FAIL
            ),
            channel=notification.channel,
            provider=getattr(self._provider, "name", None)
            or type(self._provider).__name__,
            recipient_address=recipient_address,
            provider_message_id=provider_message_id,
            error=error,
        )
        await self._attempts.save(attempt)

    async def _succeed(
        self,
        notification: Notification,
        *,
        provider_message_id: str | None,
        recipient_address: str,
    ) -> Notification:
        async with self._uow:
            await self._record_attempt(
                notification,
                success=True,
                provider_message_id=provider_message_id,
                error=None,
                recipient_address=recipient_address,
            )
            updated = notification.mark_delivered()
            await self._notifications.save(updated)
        return updated

    async def _fail(
        self,
        notification: Notification,
        *,
        error: str,
        recipient_address: str | None = None,
    ) -> Notification:
        """Record a failed attempt and transition to FAILED.

        ``recipient_address`` is the address the provider was given. It is
        ``None`` when the failure preceded any contact - the no-address
        case - so the snapshot on the attempt distinguishes "failed before
        contact" from "contacted and rejected".
        """
        async with self._uow:
            await self._record_attempt(
                notification,
                success=False,
                provider_message_id=None,
                error=error,
                recipient_address=recipient_address,
            )
            updated = notification.mark_failed(error)
            await self._notifications.save(updated)
        return updated

    async def _retry(
        self,
        notification: Notification,
        *,
        error: str,
        recipient_address: str,
    ) -> None:
        """Persist a failed provider attempt and release the notification for retry."""
        async with self._uow:
            await self._record_attempt(
                notification,
                success=False,
                provider_message_id=None,
                error=error,
                recipient_address=recipient_address,
            )
            await self._notifications.save(notification.retry_delivery())
