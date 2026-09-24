from sqlalchemy.dialects import postgresql

from ...domain.enums import (
    DeliveryAttemptStatus,
    DeliveryChannel,
    EngagementEventType,
    MLModelStatus,
    MLModelType,
    MLPriority,
    NotificationStatus,
    SendTimeBasis,
    TrainingRunStatus,
    WebhookEventType,
)


# Enum helper
def _pg_enum(enum_cls, *, name: str) -> postgresql.ENUM:
    # Build the PostgreSQL enum type from the enum's string VALUES (e.g.
    # "email", "success") so the ORM stays aligned with the database enum
    # types, which use lowercase values. Deliberately not bound to the Python
    # enum class: a StrEnum member assigned to a column is a str subclass
    # equal to its value, so it validates/persists as that lowercase value.
    values = [member.value for member in enum_cls]
    return postgresql.ENUM(*values, name=name, create_type=False)


# SQLAlchemy PostgreSQL Enum Types

DeliveryChannelType = _pg_enum(DeliveryChannel, name="delivery_channel")

NotificationStatusType = _pg_enum(NotificationStatus, name="notification_status")

DeliveryAttemptStatusType = _pg_enum(
    DeliveryAttemptStatus, name="delivery_attempt_status"
)

EngagementEventTypeType = _pg_enum(EngagementEventType, name="engagement_event_type")

SendTimeBasisType = _pg_enum(SendTimeBasis, name="send_time_basis")

MLPriorityType = _pg_enum(MLPriority, name="ml_priority")

MLModelTypeType = _pg_enum(MLModelType, name="ml_model_type")

MLModelStatusType = _pg_enum(MLModelStatus, name="ml_model_status")

TrainingRunStatusType = _pg_enum(TrainingRunStatus, name="training_run_status")

WebhookEventTypeType = _pg_enum(WebhookEventType, name="webhook_event_type")


# Auth-layer role, deliberately NOT a domain enum: roles are an auth concern
# and the domain's Account entity models ownership by id only. Plain strings
# keep the auth capability out of the domain vocabulary.
AccountRoleType = postgresql.ENUM(
    "user",
    "admin",
    name="account_role",
    create_type=False,
)
