from enum import StrEnum


class NotificationStatus(StrEnum):
    """Enum values for notification status."""

    PENDING = "pending"
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"
    POLICY_REJECTED = "policy_rejected"
    CANCELLED = "cancelled"
