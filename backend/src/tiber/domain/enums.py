from enum import StrEnum


class DeliveryChannel(StrEnum):
    """Enum values for delivery channels."""

    EMAIL = "email"
    PUSH = "push"
    SMS = "sms"
    IN_APP = "in_app"


class NotificationCategory(StrEnum):
    """Enum values for notification categories."""

    CRITICAL = "critical"
    INFORMATIONAL = "informational"
    SOCIAL = "social"
    PROMOTIONAL = "promotional"


class NotificationStatus(StrEnum):
    """Enum values for notification statuses."""

    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"  # Internal, network, or provider outages
    BOUNCED = "bounced"  # Recipient-side rejection
    SUPPRESSED = "suppressed"  # System-level intentional drops
    POSTPONED = "postponed"
    CANCELLED = "cancelled"


class PolicyConsequence(StrEnum):
    """What happens to a notification when a policy rule rejects it.

    - ``SUPPRESS`` — a permanent, intentional drop (recipient opt-outs,
      blackout periods). The notification is stored with a reason and never
      delivered.
    - ``POSTPONE`` — a temporary deferral (quiet hours). Delivery will happen
      when the restrictive window ends, so the notification is re-queued
      rather than dropped.
    """

    SUPPRESS = "suppress"
    POSTPONE = "postpone"


class SendTimeBasis(StrEnum):
    """Enum values for send time basis."""

    IMMEDIATE = "immediate"
    EXPLICIT = "explicit"
    ML_PREDICTED = "ml_predicted"


class DeliveryAttemptStatus(StrEnum):
    """Status of a delivery attempt."""

    SUCCESS = "success"
    FAIL = "fail"


class EngagementEventType(StrEnum):
    """Type of an engagement event."""

    OPEN = "open"
    CLICK = "click"
    BOUNCE = "bounce"
    COMPLAINT = "complaint"
    UNSUBSCRIBE = "unsubscribe"


class MLPriority(StrEnum):
    """Priority levels for machine learning models."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MLModelType(StrEnum):
    """Types of machine learning models."""

    PRIORITY_CLASSIFIER = "priority_classifier"
    SEND_TIME_PREDICTOR = "send_time_predictor"
    CHANNEL_PREFERENCE_PREDICTOR = "channel_preference_predictor"


class MLModelStatus(StrEnum):
    """Status of a machine learning model."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"


class TrainingRunStatus(StrEnum):
    """Status of a training run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WebhookEventType(StrEnum):
    """Types of webhook events."""

    NOTIFICATION_DELIVERED = "notification.delivered"
    NOTIFICATION_FAILED = "notification.failed"
    NOTIFICATION_BOUNCED = "notification.bounced"
    NOTIFICATION_CANCELLED = "notification.cancelled"
    NOTIFICATION_SUPPRESSED = "notification.suppressed"
