from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import (
    DeliveryChannel,
    NotificationCategory,
    NotificationStatus,
    SendTimeBasis,
)
from ..exceptions import InvalidNotificationStateError, InvalidStateTransitionError
from ..value_objects import NotificationContent


@dataclass(frozen=True, kw_only=True)
class Notification:
    """Notification entity."""

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    recipient_id: UUID
    correlation_id: UUID
    channel: DeliveryChannel
    category: NotificationCategory
    content: NotificationContent

    # Optional / nullable fields

    status: NotificationStatus = NotificationStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    template_id: UUID | None = None
    template_variables: dict[str, str] | None = None
    idempotency_key: str | None = None
    send_at: datetime | None = None
    send_time_basis: SendTimeBasis = SendTimeBasis.IMMEDIATE
    policy_violation_reason: str | None = None
    failure_reason: str | None = None
    delivered_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the notification entity's state after initialization."""
        # 1. send_time_basis vs send_at
        if self.send_time_basis == SendTimeBasis.EXPLICIT and self.send_at is None:
            raise InvalidNotificationStateError(
                "`send_at` is required when `send_time_basis` is EXPLICIT"
            )
        if self.send_time_basis == SendTimeBasis.IMMEDIATE and self.send_at is not None:
            raise InvalidNotificationStateError(
                "`send_at` must not be set when `send_time_basis` is IMMEDIATE"
            )

        # 2. policy_rejected to reason consistency
        if self.status == NotificationStatus.POLICY_REJECTED:
            if self.policy_violation_reason is None:
                raise InvalidNotificationStateError(
                    "`policy_violation_reason` is required when status is POLICY_REJECTED"
                )
        else:
            if self.policy_violation_reason is not None:
                raise InvalidNotificationStateError(
                    "`policy_violation_reason` must only be set when status is POLICY_REJECTED"
                )

        # 2b. failed to reason consistency
        if self.status == NotificationStatus.FAILED:
            if self.failure_reason is None:
                raise InvalidNotificationStateError(
                    "`failure_reason` is required when status is FAILED"
                )
        else:
            if self.failure_reason is not None:
                raise InvalidNotificationStateError(
                    "`failure_reason` must only be set when status is FAILED"
                )

        # 3. email channel requires subject; other channels must not have one
        if self.channel == DeliveryChannel.EMAIL:
            if self.content.subject is None:
                raise InvalidNotificationStateError(
                    "Email notifications must have a subject"
                )
        else:
            if self.content.subject is not None:
                raise InvalidNotificationStateError(
                    f"Subject must not be set for {self.channel.value} notifications"
                )

        # 4. delivered status ↔ delivered_at consistency
        if self.status == NotificationStatus.DELIVERED:
            if self.delivered_at is None:
                raise InvalidNotificationStateError(
                    "`delivered_at` is required when status is DELIVERED"
                )
        else:
            if self.delivered_at is not None:
                raise InvalidNotificationStateError(
                    "`delivered_at` must only be set when status is DELIVERED"
                )

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        recipient_id: UUID,
        correlation_id: UUID,
        channel: DeliveryChannel,
        category: NotificationCategory,
        content: NotificationContent,
        template_id: UUID | None = None,
        template_variables: dict[str, str] | None = None,
        idempotency_key: str | None = None,
        send_at: datetime | None = None,
        send_time_basis: SendTimeBasis = SendTimeBasis.IMMEDIATE,
    ) -> Notification:
        """Create a new pending notification with system-generated identity.

        This is the primary creation path: the id and timestamps are generated
        here, and the notification always starts PENDING. Terminal states and
        their coupled fields (policy_violation_reason, failure_reason,
        delivered_at) are unreachable from here on purpose - they arise only
        through state transitions.
        """
        return cls(
            project_id=project_id,
            recipient_id=recipient_id,
            correlation_id=correlation_id,
            channel=channel,
            category=category,
            content=content,
            template_id=template_id,
            template_variables=template_variables,
            idempotency_key=idempotency_key,
            send_at=send_at,
            send_time_basis=send_time_basis,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        recipient_id: UUID,
        correlation_id: UUID,
        channel: DeliveryChannel,
        category: NotificationCategory,
        content: NotificationContent,
        status: NotificationStatus,
        created_at: datetime,
        updated_at: datetime,
        template_id: UUID | None,
        template_variables: dict[str, str] | None,
        idempotency_key: str | None,
        send_at: datetime | None,
        send_time_basis: SendTimeBasis,
        policy_violation_reason: str | None,
        failure_reason: str | None,
        delivered_at: datetime | None,
    ) -> Notification:
        """Rebuild an existing notification from persisted state.

        Every field is required with no default: a reconstituted entity must
        receive the full stored row, including its identity and timestamps.
        Forgetting one is a TypeError, never silently regenerated state.
        """
        return cls(
            id=id,
            project_id=project_id,
            recipient_id=recipient_id,
            correlation_id=correlation_id,
            channel=channel,
            category=category,
            content=content,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            template_id=template_id,
            template_variables=template_variables,
            idempotency_key=idempotency_key,
            send_at=send_at,
            send_time_basis=send_time_basis,
            policy_violation_reason=policy_violation_reason,
            failure_reason=failure_reason,
            delivered_at=delivered_at,
        )

    def _transition(
        self,
        status: NotificationStatus,
        **changes,
    ):
        return replace(
            self,
            status=status,
            updated_at=datetime.now(UTC),
            **changes,
        )

    def with_content(self, content: NotificationContent) -> Notification:
        """Return this notification with a replaced content snapshot."""
        return replace(self, content=content, updated_at=datetime.now(UTC))

    def mark_processing(self) -> Notification:
        """Transition the notification from pending to the in-flight processing state.

        Marks the notification as being actively worked by a worker so that a
        duplicate or concurrent dispatch of the same id will no longer see it as
        PENDING and therefore will not re-deliver. Processing is transient - a
        terminal transition (delivered/failed/...) is expected next.
        """
        if self.status != NotificationStatus.PENDING:
            raise InvalidStateTransitionError(
                self.status, NotificationStatus.PROCESSING
            )

        return self._transition(status=NotificationStatus.PROCESSING)

    def mark_cancelled(self) -> Notification:
        """Transition the notification to the cancelled state."""
        if self.status != NotificationStatus.PENDING:
            raise InvalidStateTransitionError(self.status, NotificationStatus.CANCELLED)

        return self._transition(status=NotificationStatus.CANCELLED)

    def mark_policy_rejected(self, reason: str) -> Notification:
        """Transition the notification to the policy_rejected state."""
        if self.status != NotificationStatus.PENDING:
            raise InvalidStateTransitionError(
                self.status, NotificationStatus.POLICY_REJECTED
            )
        if not reason:
            raise InvalidNotificationStateError(
                "policy_violation_reason is required when rejecting"
            )

        return self._transition(
            status=NotificationStatus.POLICY_REJECTED,
            policy_violation_reason=reason,
        )

    def mark_delivered(self) -> Notification:
        """Transition the notification to the delivered state.

        Allowed from both PENDING (immediate dispatch) and PROCESSING
        (after the processing guard has run).
        """
        if self.status not in (
            NotificationStatus.PENDING,
            NotificationStatus.PROCESSING,
        ):
            raise InvalidStateTransitionError(self.status, NotificationStatus.DELIVERED)

        return self._transition(
            status=NotificationStatus.DELIVERED,
            delivered_at=datetime.now(UTC),
        )

    def mark_failed(self, reason: str) -> Notification:
        """Transition the notification to the failed state.

        A failure must carry its reason: the row is the permanent, queryable
        record of why delivery ended in failure, so an unexplained failure is
        not representable. Allowed from both PENDING (immediate dispatch) and
        PROCESSING (after the processing guard has run).
        """
        if self.status not in (
            NotificationStatus.PENDING,
            NotificationStatus.PROCESSING,
        ):
            raise InvalidStateTransitionError(self.status, NotificationStatus.FAILED)
        if not reason:
            raise InvalidNotificationStateError(
                "failure_reason is required when failing"
            )

        return self._transition(
            status=NotificationStatus.FAILED,
            failure_reason=reason,
        )
