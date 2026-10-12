from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tiber.application.ports.idempotency import IdempotencyGuard
from tiber.application.ports.message_publisher import MessagePublisher
from tiber.application.services.channel_resolver import ChannelResolver
from tiber.application.services.template import NotificationTemplateResolver
from tiber.domain.entities import Notification, Recipient
from tiber.domain.enums import (
    DeliveryChannel,
    NotificationCategory,
    NotificationStatus,
    PolicyConsequence,
    SendTimeBasis,
)
from tiber.domain.exceptions import (
    AddressConflictError,
    AmbiguousRecipientError,
    EntityNotFoundError,
    RecipientAddressTakenError,
)
from tiber.domain.policies import PolicyResolver
from tiber.domain.repositories import (
    DeliveryConstraintRepository,
    NotificationRepository,
    RecipientRepository,
)
from tiber.domain.services import validate_content
from tiber.domain.services.addresses import normalize_addresses
from tiber.domain.value_objects import NotificationContent


@dataclass(frozen=True)
class CreatedBatch:
    """Result of an intake request: one notification per resolved channel."""

    correlation_id: UUID
    notifications: list[Notification]
    recipient: Recipient
    replayed: bool = False


class NotificationService:
    """Application use case for notification intake.

    Intake resolves and renders template content, validates scoping and
    delivery policy, then persists a snapshot of the final content before
    enqueueing. The persisted notification is the actual content that will be
    delivered — never a ``[template pending]`` placeholder (the placeholder
    is only ever used transiently to build a provisional entity for template
    resolution).
    """

    def __init__(
        self,
        *,
        idempotency_guard: IdempotencyGuard,
        repository: NotificationRepository,
        publisher: MessagePublisher,
        recipient_repository: RecipientRepository,
        template_resolver: NotificationTemplateResolver,
        policy_resolver: PolicyResolver,
        channel_resolver: ChannelResolver,
        constraint_repository: DeliveryConstraintRepository | None = None,
    ) -> None:
        """Initialize the service with its ports and intake collaborators."""
        self._idempotency = idempotency_guard
        self._repository = repository
        self._publisher = publisher
        self._recipients = recipient_repository
        self._template_resolver = template_resolver
        self._policy = policy_resolver
        self._channels = channel_resolver
        self._constraints = constraint_repository

    @staticmethod
    def _build(
        *,
        project_id: UUID,
        recipient_id: UUID,
        correlation_id: UUID,
        channel: DeliveryChannel,
        category: NotificationCategory,
        content: NotificationContent,
        topic_id: UUID | None,
        template_id: UUID | None,
        template_variables: dict | None,
        idempotency_key: str,
        send_at: datetime | None,
    ) -> Notification:
        """Build a notification entity; the entity derives its send-time basis."""
        if send_at is not None:
            send_time_basis = SendTimeBasis("explicit")
        elif category is NotificationCategory.CRITICAL:
            send_time_basis = SendTimeBasis("immediate")
        else:
            send_time_basis = SendTimeBasis("ml_predicted")

        return Notification.create(
            project_id=project_id,
            recipient_id=recipient_id,
            correlation_id=correlation_id,
            channel=channel,
            category=category,
            content=content,
            topic_id=topic_id,
            template_id=template_id,
            template_variables=template_variables,
            idempotency_key=idempotency_key,
            send_at=send_at,
            send_time_basis=send_time_basis,
        )

    async def create_notification(
        self,
        *,
        project_id: UUID,
        recipient_id: str | None,
        addresses: Mapping[DeliveryChannel, str],
        channels: list[DeliveryChannel] | None,
        category: NotificationCategory | None,
        topic_slug: str | None,
        idempotency_key: str,
        correlation_id: UUID,
        content: NotificationContent | None,
        template_slug: str | None = None,
        template_variables: dict | None = None,
        group_key: str | None,
        send_at: datetime | None = None,
    ) -> CreatedBatch:
        """Create, persist, and enqueue a notification.

        Idempotent: a repeated submission with the same ``(project, key)``
        within the TTL window returns the originally persisted notification
        instead of creating another.

        Intake-time steps, in order:

        1. Idempotency replay (return the original on a duplicate key).
        2. Validate recipient scoping: the recipient must exist and belong to
           the project.
        3. Resolve/validate/render template content (ownership, channel) so
           the persisted body is the rendered snapshot. Direct content
           (``template_id`` is None) requires a body.
        4. Evaluate the delivery policy. A violation's consequence decides
           the outcome: SUPPRESS persists the notification with a reason and
           it is never delivered; POSTPONE persists it with a resume time
           (after the violated quiet window) and enqueues delivery for that
           time. An allowed notification is persisted then enqueued.
        """
        if recipient_id is not None and addresses:
            raise ValueError("Provide either `recipient_id` or addresses, not both")

        # 1. Idempotency check. Replay: the guard stores the base key against the first child.
        replay = await self._replay(project_id, idempotency_key)
        if replay is not None:
            return replay
        # 2. Recipient (registered, matched, or newly created and persisted).
        recipient = await self._resolve_recipient(project_id, recipient_id, addresses)
        adhoc = recipient_id is None

        # 3. Channels. For address-based requests the request itself defines
        #    the set, not whatever the matched recipient has accumulated.
        resolved = await self._channels.resolve(
            recipient=recipient,
            requested=channels,
            category=category,
            adhoc_channels=frozenset(addresses) if adhoc else None,
        )

        # 4. Build every child in memory. No saves or publishes yet.
        template_id = (
            await self._template_resolver.id_for_slug(project_id, template_slug)
            if template_slug is not None
            else None
        )
        constraint = (
            await self._constraints.load_constraint(project_id)
            if self._constraints is not None
            else None
        )

        children: list[Notification] = []
        for channel in resolved:
            child = await self._build_child(
                channel=channel,
                content=content,
                template_id=template_id,
                project_id=project_id,
                recipient_id=recipient.id,
                correlation_id=correlation_id,
                category=category,
                topic_id=topic_slug,
                template_variables=template_variables,
                group_key=group_key,
                # Unique per child; the client's key is stripped on output.
                idempotency_key=f"{idempotency_key}:{channel.value}",
                send_at=send_at,
            )
            children.append(await self._apply_policy(child, recipient, constraint))

        if not children:  # defensive: the resolver never returns an empty set
            raise ValueError("No channels resolved for notification")

        # 5. Persist everything, record the key, then publish.
        # ``save`` flushes; a concurrent duplicate key surfaces as IntegrityError.
        for child in children:
            await self._repository.save(child)
        await self._idempotency.check_and_store(
            project_id, idempotency_key, children[0].id
        )

        for child in children:
            if child.status in (
                NotificationStatus.PENDING,
                NotificationStatus.POSTPONED,
            ):
                await self._publisher.publish_notification(child)

        return CreatedBatch(correlation_id, children, recipient)

    async def get_notification(
        self, project_id: UUID, notification_id: UUID
    ) -> Notification:
        """Fetch notification."""
        notification = await self._repository.get_by_id(notification_id, project_id)
        if notification is None or notification.project_id != project_id:
            raise EntityNotFoundError(Notification, str(notification_id))
        return notification

    async def list_batch(
        self, project_id: UUID, correlation_id: UUID
    ) -> list[Notification]:
        """Every notification created by one request."""
        return await self._repository.list_by_correlation_id(correlation_id, project_id)

    async def list_notifications(
        self, project_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[Notification]:
        """Get all notifications in a project."""
        return await self._repository.list_by_project(project_id, limit, offset)

    async def _replay(self, project_id: UUID, key: str) -> CreatedBatch | None:
        notif_id = await self._idempotency.get_existing_notification_id(project_id, key)
        if notif_id is None:
            return None
        notification = await self._repository.get_by_id(notif_id, project_id)
        if notification is None:
            return None
        batch_notification = await self._repository.list_by_correlation_id(
            notification.correlation_id, project_id
        )
        recipient = await self._recipients.get_by_id(
            notification.recipient_id, project_id
        )
        if recipient is None:
            return None
        return CreatedBatch(
            notification.correlation_id, batch_notification, recipient, replayed=True
        )

    async def _resolve_recipient(
        self,
        project_id: UUID,
        recipient_id: str | None,
        addresses: Mapping[DeliveryChannel, str],
    ) -> Recipient:
        if recipient_id is not None:
            recipient = await self._recipients.get_by_external_id(
                recipient_id, project_id
            )
            if recipient is None:
                raise EntityNotFoundError(Recipient, recipient_id)
            return recipient
        return await self._resolve_adhoc(project_id, addresses)

    async def _resolve_adhoc(
        self, project_id: UUID, addresses: Mapping[DeliveryChannel, str]
    ) -> Recipient:
        """Match supplied addresses to an existing recipient, or create one.

        * zero matches    -> create and persist
        * one match       -> reuse; add channels it lacks (append-only)
        * several matches -> AmbiguousRecipientError (merge is the client's call)
        * different address on an existing channel -> AddressConflictError
        """
        if not addresses:
            raise ValueError("Address-based requests need at least one address")
        normalized = normalize_addresses(addresses)

        for _ in range(2):  # second pass only after losing a creation race
            matches = {
                r.id: r
                for r in await self._recipients.find_by_addresses(
                    project_id, normalized
                )
            }

            if len(matches) > 1:
                raise AmbiguousRecipientError(
                    "Supplied addresses belong to different recipients. "
                    "Send them in separate requests or register a recipient."
                )

            if not matches:
                try:
                    return await self._recipients.add(
                        Recipient.create(project_id=project_id, addresses=normalized)
                    )
                except RecipientAddressTakenError:
                    continue  # someone created it first; re-read

            return await self._extend(next(iter(matches.values())), normalized)

        raise AmbiguousRecipientError("Could not resolve recipient; retry the request.")

    async def _extend(
        self, existing: Recipient, supplied: Mapping[DeliveryChannel, str]
    ) -> Recipient:
        conflicts = sorted(
            ch.value
            for ch, addr in supplied.items()
            if ch in existing.addresses and existing.addresses[ch] != addr
        )
        if conflicts:
            raise AddressConflictError(
                f"Recipient already has a different address for: {conflicts}"
            )

        new = {ch: a for ch, a in supplied.items() if ch not in existing.addresses}
        if not new:
            return existing

        # update_addresses replaces the whole book, so pass a fresh merged dict.
        updated = existing.update_addresses({**existing.addresses, **new})
        try:
            await self._recipients.save(updated)
        except RecipientAddressTakenError as exc:  # claimed concurrently elsewhere
            raise AmbiguousRecipientError(
                "A supplied address belongs to another recipient."
            ) from exc
        return updated

    async def _build_child(
        self,
        *,
        channel: DeliveryChannel,
        content: NotificationContent | None,
        template_id: UUID | None,
        **fields,
    ) -> Notification:
        if template_id is not None:
            # The placeholder only exists to build a provisional entity the
            # template resolver can render against; it is never persisted.
            placeholder = NotificationContent(
                body="[template pending]",
                title="[template pending]"
                if channel is DeliveryChannel.EMAIL
                else None,
            )
            provisional = self._build(
                channel=channel,
                content=placeholder,
                template_id=template_id,
                **fields,
            )
            rendered = await self._template_resolver.resolve_content(provisional)
            return provisional.with_content(rendered)

        if content is None:
            raise ValueError("Notification content is required without a template")
        # Same direct content on every channel, validated against each one.
        validate_content(channel, content)
        return self._build(channel=channel, content=content, template_id=None, **fields)

    async def _apply_policy(
        self, notification: Notification, recipient: Recipient, constraint
    ) -> Notification:
        """Map the policy decision onto the state machine."""
        decision = await self._policy.evaluate(notification, recipient, constraint)
        if decision.allowed:
            return notification
        if decision.consequence is PolicyConsequence.POSTPONE:
            if decision.resume_at is None:
                raise ValueError("policy returned POSTPONE without a resume time")
            return notification.mark_postponed(decision.resume_at)
        return notification.mark_suppressed(decision.reason or "policy violation")
