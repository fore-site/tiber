from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ..enums import Channel, NotificationStatus, SendTimeBasis
from ..exceptions import InvalidNotificationStateError, InvalidStateTransitionError
from ..value_objects import NotificationContent


@dataclass(frozen=True)
class Notification:
    """Notification entity."""

    id: UUID
    project_id: UUID
    recipient_id: UUID
    correlation_id: UUID
    channel: Channel
    content: NotificationContent
    status: NotificationStatus = NotificationStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Optional / nullable fields
    template_id: UUID | None = None
    template_variables: dict[str, Any] | None = None
    idempotency_key: str | None = None
    scheduled_at: datetime | None = None
    send_time_basis: SendTimeBasis = SendTimeBasis.IMMEDIATE
    policy_violation_reason: str | None = None
    delivered_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the notification entity's state after initialization."""
        # 1. send_time_basis vs scheduled_at
        if self.send_time_basis == SendTimeBasis.EXPLICIT and self.scheduled_at is None:
            raise InvalidNotificationStateError(
                "`scheduled_at` is required when `send_time_basis` is EXPLICIT"
            )
        if (
            self.send_time_basis == SendTimeBasis.IMMEDIATE
            and self.scheduled_at is not None
        ):
            raise InvalidNotificationStateError(
                "`scheduled_at` must not be set when `send_time_basis` is IMMEDIATE"
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

        # 3. email channel requires subject; other channels must not have one
        if self.channel == Channel.EMAIL:
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

    def _transition(
        self,
        status: NotificationStatus,
        **changes,
    ):
        return replace(
            self,
            status=status,
            **changes,
        )

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
        """Transition the notification to the delivered state."""
        if self.status != NotificationStatus.PENDING:
            raise InvalidStateTransitionError(self.status, NotificationStatus.DELIVERED)

        return self._transition(
            status=NotificationStatus.DELIVERED,
            delivered_at=datetime.now(UTC),
        )

    def mark_failed(self) -> Notification:
        """Transition the notification to the failed state."""
        if self.status != NotificationStatus.PENDING:
            raise InvalidStateTransitionError(self.status, NotificationStatus.FAILED)

        return self._transition(status=NotificationStatus.FAILED)
