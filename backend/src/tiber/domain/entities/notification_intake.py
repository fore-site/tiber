"""NotificationIntake: the accepted request, before it is expanded into notifications.

The API validates everything the client can act on, persists an intake plus an
outbox message in one transaction, and returns. A worker later claims the
intake, asks the ML for the decisions the client left open, and fans out one
``Notification`` per channel.
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from tiber.domain.enums import IntakeStatus
from tiber.domain.exceptions import (
    InvalidEntityAttributeError,
    InvalidStateTransitionError,
)
from tiber.domain.value_objects.intake import (
    DecisionConstraints,
    IntakePayload,
    NotificationPlan,
)


@dataclass(frozen=True, kw_only=True)
class NotificationIntake:
    """Intake entity."""

    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    correlation_id: UUID = field(default_factory=uuid4)
    recipient_id: (
        UUID  # internal id of the resolved (registered, matched or new) recipient
    )
    payload: IntakePayload
    constraints: DecisionConstraints
    request_fingerprint: (
        str  # detects an idempotency key reused with a different payload
    )

    idempotency_key: str | None = None
    status: IntakeStatus = IntakeStatus.RECEIVED
    plan: NotificationPlan | None = None
    attempts: int = 0
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate invariants after initialization."""
        if self.attempts < 0:
            raise InvalidEntityAttributeError("`attempts` must not be negative")
        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise InvalidEntityAttributeError(
                "`idempotency_key` must be a non-empty string when provided"
            )
        for name in ("claimed_at", "completed_at"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise InvalidEntityAttributeError(f"`{name}` must be timezone-aware")

        if self.status is IntakeStatus.RECEIVED and (
            self.plan is not None or self.claimed_at is not None
        ):
            raise InvalidEntityAttributeError(
                "A RECEIVED intake has no plan and has not been claimed"
            )
        if self.status is IntakeStatus.PROCESSING and self.claimed_at is None:
            raise InvalidEntityAttributeError(
                "`claimed_at` is required when status is PROCESSING"
            )

        if self.status is IntakeStatus.COMPLETED:
            if self.plan is None or self.completed_at is None:
                raise InvalidEntityAttributeError(
                    "`plan` and `completed_at` are required when status is COMPLETED"
                )
        elif self.completed_at is not None:
            raise InvalidEntityAttributeError(
                "`completed_at` must only be set when status is COMPLETED"
            )

        if self.status is IntakeStatus.FAILED:
            if not self.failure_reason:
                raise InvalidEntityAttributeError(
                    "`failure_reason` is required when status is FAILED"
                )
        elif self.failure_reason is not None:
            raise InvalidEntityAttributeError(
                "`failure_reason` must only be set when status is FAILED"
            )

    # Construction

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        recipient_id: UUID,
        payload: IntakePayload,
        constraints: DecisionConstraints,
        request_fingerprint: str,
        correlation_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> NotificationIntake:
        """Create a RECEIVED intake with a system-generated identity.

        ``correlation_id`` is generated here when the caller does not supply one;
        it is the batch handle every child notification shares.
        """
        return cls(
            project_id=project_id,
            correlation_id=correlation_id or uuid4(),
            recipient_id=recipient_id,
            payload=payload,
            constraints=constraints,
            request_fingerprint=request_fingerprint,
            idempotency_key=idempotency_key,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        correlation_id: UUID,
        recipient_id: UUID,
        payload: IntakePayload,
        constraints: DecisionConstraints,
        request_fingerprint: str,
        idempotency_key: str | None,
        status: IntakeStatus,
        plan: NotificationPlan | None,
        attempts: int,
        claimed_at: datetime | None,
        completed_at: datetime | None,
        failure_reason: str | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> NotificationIntake:
        """Rebuild an intake from persisted state; every field is required."""
        return cls(
            id=id,
            project_id=project_id,
            correlation_id=correlation_id,
            recipient_id=recipient_id,
            payload=payload,
            constraints=constraints,
            request_fingerprint=request_fingerprint,
            idempotency_key=idempotency_key,
            status=status,
            plan=plan,
            attempts=attempts,
            claimed_at=claimed_at,
            completed_at=completed_at,
            failure_reason=failure_reason,
            created_at=created_at,
            updated_at=updated_at,
        )

    # Transitions

    def _transition(self, status: IntakeStatus, **changes) -> NotificationIntake:
        return replace(self, status=status, updated_at=datetime.now(UTC), **changes)

    def is_claimable(self, now: datetime, lease: timedelta) -> bool:
        """RECEIVED, or PROCESSING with a lease that has expired (worker crashed)."""
        if self.status is IntakeStatus.RECEIVED:
            return True
        if self.status is IntakeStatus.PROCESSING and self.claimed_at:
            return self.claimed_at + lease <= now
        return False

    def claim(self, now: datetime, lease: timedelta) -> NotificationIntake:
        """Take (or retake) the processing lease.

        Keeps any stored plan, so a retry reuses the earlier ML decision instead of inferring again.
        """
        if not self.is_claimable(now, lease):
            raise InvalidStateTransitionError(self.status, IntakeStatus.PROCESSING)
        if now.tzinfo is None:
            raise InvalidEntityAttributeError("`now` must be timezone-aware")
        return self._transition(
            IntakeStatus.PROCESSING, claimed_at=now, attempts=self.attempts + 1
        )

    def with_plan(self, plan: NotificationPlan) -> NotificationIntake:
        """Store the decision before fan-out. Only while PROCESSING."""
        if self.status is not IntakeStatus.PROCESSING:
            raise InvalidEntityAttributeError(
                "`with_plan` is only valid while the intake is PROCESSING"
            )
        return replace(self, plan=plan, updated_at=datetime.now(UTC))

    def complete(self, now: datetime) -> NotificationIntake:
        """Mark fan-out done. Requires a stored plan."""
        if self.status is not IntakeStatus.PROCESSING:
            raise InvalidStateTransitionError(self.status, IntakeStatus.COMPLETED)
        if self.plan is None:
            raise InvalidEntityAttributeError(
                "Cannot complete an intake without a plan"
            )
        return self._transition(IntakeStatus.COMPLETED, completed_at=now)

    def fail(self, reason: str) -> NotificationIntake:
        """Record a deterministic failure. Legal from RECEIVED or PROCESSING."""
        if self.status not in (IntakeStatus.RECEIVED, IntakeStatus.PROCESSING):
            raise InvalidStateTransitionError(self.status, IntakeStatus.FAILED)
        if not reason:
            raise InvalidEntityAttributeError("failure_reason is required when failing")
        return self._transition(IntakeStatus.FAILED, failure_reason=reason)
