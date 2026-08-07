from enum import StrEnum


class DeliveryChannel(StrEnum):
    """Enum values for delivery channels."""

    EMAIL = "email"
    PUSH = "push"
    SMS = "sms"
    WEBHOOK = "webhook"
    IN_APP = "in_app"


class NotificationStatus(StrEnum):
    """Enum values for notification statuses."""

    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"
    POLICY_REJECTED = "policy_rejected"
    CANCELLED = "cancelled"


class SendTimeBasis(StrEnum):
    """Enum values for send time basis."""

    IMMEDIATE = "immediate"
    EXPLICIT = "explicit"
    ML_PREDICTED = "ml_predicted"


class UserRole(StrEnum):
    """User role for access control."""

    ADMIN = "admin"
    USER = "user"


class DeliveryAttemptStatus(StrEnum):
    """Status of a delivery attempt."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WebhookEventStatus(StrEnum):
    """Status of a webhook event."""

    DELIVERED = "delivered"
    FAILED = "failed"


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
    NOTIFICATION_CANCELLED = "notification.cancelled"
    NOTIFICATION_POLICY_REJECTED = "notification.policy_rejected"
