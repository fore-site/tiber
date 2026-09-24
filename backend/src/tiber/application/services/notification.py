from datetime import datetime
from uuid import UUID

from tiber.application.ports.idempotency import IdempotencyGuard
from tiber.application.ports.message_publisher import MessagePublisher
from tiber.application.services.template import NotificationTemplateResolver
from tiber.domain.entities import Notification
from tiber.domain.enums import DeliveryChannel, NotificationCategory, PolicyConsequence
from tiber.domain.exceptions import (
    NotificationNotFoundError,
    RecipientNotFoundError,
)
from tiber.domain.policies import PolicyResolver
from tiber.domain.repositories import (
    DeliveryConstraintRepository,
    NotificationRepository,
    RecipientRepository,
)
from tiber.domain.services import validate_content
from tiber.domain.value_objects import NotificationContent


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
        constraint_repository: DeliveryConstraintRepository | None = None,
    ) -> None:
        """Initialize the service with its ports and intake collaborators."""
        self._idempotency = idempotency_guard
        self._repository = repository
        self._publisher = publisher
        self._recipients = recipient_repository
        self._template_resolver = template_resolver
        self._policy = policy_resolver
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
        template_id: UUID | None,
        template_variables: dict | None,
        idempotency_key: str,
        scheduled_at: datetime | None,
    ) -> Notification:
        """Build a notification entity; the entity derives its send-time basis."""
        return Notification.create(
            project_id=project_id,
            recipient_id=recipient_id,
            correlation_id=correlation_id,
            channel=channel,
            category=category,
            content=content,
            template_id=template_id,
            template_variables=template_variables,
            idempotency_key=idempotency_key,
            send_at=scheduled_at,
        )

    async def create_notification(
        self,
        *,
        project_id: UUID,
        recipient_id: UUID,
        channel: str,
        category: str,
        idempotency_key: str,
        correlation_id: UUID,
        title: str | None = None,
        body: str | None = None,
        template_id: UUID | None = None,
        template_variables: dict | None = None,
        scheduled_at: datetime | None = None,
    ) -> Notification:
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
        # 1. Idempotency check - replay the original on a duplicate key.
        existing_id = await self._idempotency.get_existing_notification_id(
            project_id,
            idempotency_key,
        )
        if existing_id is not None:
            existing = await self._repository.get_by_id(existing_id, project_id)
            if existing is not None:
                return existing

        channel_enum = DeliveryChannel(channel)
        category_enum = NotificationCategory(category)

        # 2. Recipient must exist within the project. The lookup is scoped:
        # a cross-project id reads as a miss, not a foreign row.
        recipient = await self._recipients.get_by_id(recipient_id, project_id)
        if recipient is None:
            raise RecipientNotFoundError(str(recipient_id))

        # 3. Resolve and render template content at intake. The template
        # resolver validates ownership and channel; rendering produces the
        # exact content snapshot that is persisted and, later, delivered.
        if template_id is not None:
            placeholder = NotificationContent(
                title=(
                    "[template pending]"
                    if channel_enum == DeliveryChannel.EMAIL
                    else None
                ),
                body="[template pending]",
            )
            provisional = self._build(
                project_id=project_id,
                recipient_id=recipient_id,
                correlation_id=correlation_id,
                channel=channel_enum,
                category=category_enum,
                content=placeholder,
                template_id=template_id,
                template_variables=template_variables,
                idempotency_key=idempotency_key,
                scheduled_at=scheduled_at,
            )
            content = await self._template_resolver.resolve_content(provisional)
        else:
            if body is None:
                raise ValueError("Notification body is required without a template")
            content = NotificationContent(title=title, body=body)
            # Intake-time channel validation: the domain owns the rule, the
            # application invokes it before the notification is persisted.
            # Template content is validated where the template is created.
            validate_content(channel_enum, content)

        # 4. Build the (pending) notification and run the intake policy.
        # The project's delivery constraint is loaded for evaluation; a
        # missing configuration is the permissive default, not an error.
        notification = self._build(
            project_id=project_id,
            recipient_id=recipient_id,
            correlation_id=correlation_id,
            channel=channel_enum,
            category=category_enum,
            content=content,
            template_id=template_id,
            template_variables=template_variables,
            idempotency_key=idempotency_key,
            scheduled_at=scheduled_at,
        )

        constraint = (
            await self._constraints.load_constraint(project_id)
            if self._constraints is not None
            else None
        )
        decision = await self._policy.evaluate(notification, recipient, constraint)
        if not decision.allowed:
            # The consequence is domain vocabulary: the application maps it
            # onto the state machine without inspecting rule names.
            if decision.consequence is PolicyConsequence.POSTPONE:
                if decision.resume_at is None:
                    raise ValueError("policy returned POSTPONE without a resume time")
                rejected = notification.mark_postponed(decision.resume_at)
            else:
                rejected = notification.mark_suppressed(
                    decision.reason or "policy violation"
                )
            # Persist the suppressed/postponed notification but do not
            # enqueue it for immediate delivery - it is a created record,
            # not an error response. A postponed notification's send_at is
            # the resume time, so the published job defers to it naturally.
            await self._repository.save(rejected)
            await self._idempotency.check_and_store(
                project_id,
                idempotency_key,
                rejected.id,
            )
            if decision.consequence is PolicyConsequence.POSTPONE:
                await self._publisher.publish_notification(rejected)
            return rejected

        # 5. Persist, record the idempotency key, then enqueue.
        # The save() flush may raise an IntegrityError if a concurrent request
        # created the same idempotency key; that surfaces to the caller.
        await self._repository.save(notification)
        await self._idempotency.check_and_store(
            project_id,
            idempotency_key,
            notification.id,
        )
        await self._publisher.publish_notification(notification)

        return notification

    async def get_notification(
        self, project_id: UUID, notification_id: UUID
    ) -> Notification:
        """Get a notification scoped to a project."""
        notification = await self._repository.get_by_id(notification_id, project_id)
        if notification is None or notification.project_id != project_id:
            raise NotificationNotFoundError(str(notification_id))
        return notification

    async def list_notifications(
        self, project_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[Notification]:
        """List notifications for a project with pagination."""
        return await self._repository.list_by_project(project_id, limit, offset)
