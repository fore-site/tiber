from enum import StrEnum


class NotificationStatus(StrEnum):
    """Enum values for notification status."""

    PENDING = "pending"
    POLICY_REJECTED = "policy_rejected"
    CANCELLED = "cancelled"
    DELIVERED = "delivered"
    FAILED = "failed"
