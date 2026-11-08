"""SQLAlchemy persistence adapter for :class:`NotificationIntake`."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities.notification_intake import NotificationIntake
from ...domain.enums import DeliveryChannel, IntakeStatus, NotificationCategory
from ...domain.exceptions import IntakeAlreadyExistsError
from ...domain.repositories import NotificationIntakeRepository
from ...domain.value_objects import NotificationContent
from ...domain.value_objects.intake import (
    DecisionConstraints,
    IntakePayload,
    NotificationPlan,
    ResolvedTopic,
)
from ...infrastructure.models.notification_intake import NotificationIntakeModel

JsonObject = dict[str, Any]


def _object(value: object, name: str) -> JsonObject:
    """Return a JSON object or fail with a useful persistence error."""
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _array(value: object, name: str) -> list[Any]:
    """Return a JSON array or fail with a useful persistence error."""
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    return value


def _datetime(value: object, name: str) -> datetime:
    """Decode an ISO-8601 timestamp from a persisted JSON object."""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO-8601 string")
    return datetime.fromisoformat(value)


def _optional_datetime(value: object, name: str) -> datetime | None:
    """Decode an optional ISO-8601 timestamp."""
    return None if value is None else _datetime(value, name)


def _uuid(value: object, name: str) -> UUID:
    """Decode a UUID from its JSON string representation."""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a UUID string")
    return UUID(value)


def _topic_to_json(topic: ResolvedTopic) -> JsonObject:
    """Serialize a resolved topic snapshot."""
    return {
        "id": str(topic.id),
        "slug": topic.slug,
        "category": topic.category.value,
    }


def _topic_from_json(value: object) -> ResolvedTopic:
    """Deserialize a resolved topic snapshot."""
    data = _object(value, "topic")
    return ResolvedTopic(
        id=_uuid(data.get("id"), "topic.id"),
        slug=str(data["slug"]),
        category=NotificationCategory(str(data["category"])),
    )


def _payload_to_json(payload: IntakePayload) -> JsonObject:
    """Serialize the validated request snapshot."""
    return {
        "category": payload.category.value if payload.category else None,
        "topic": _topic_to_json(payload.topic) if payload.topic else None,
        "channels": (
            [channel.value for channel in payload.channels]
            if payload.channels is not None
            else None
        ),
        "adhoc_channels": (
            sorted(channel.value for channel in payload.adhoc_channels)
            if payload.adhoc_channels is not None
            else None
        ),
        "template_id": str(payload.template_id) if payload.template_id else None,
        "template_slug": payload.template_slug,
        "template_variables": payload.template_variables,
        "content": payload.content.to_dict() if payload.content else None,
        "group_key": payload.group_key,
        "send_at": payload.send_at.isoformat() if payload.send_at else None,
    }


def _payload_from_json(value: object) -> IntakePayload:
    """Deserialize the validated request snapshot."""
    data = _object(value, "payload")
    raw_channels = data.get("channels")
    raw_adhoc_channels = data.get("adhoc_channels")
    raw_variables = data.get("template_variables")
    raw_content = data.get("content")
    legacy_html_body = data.get("html_body")

    if raw_variables is not None and not isinstance(raw_variables, dict):
        raise ValueError("payload.template_variables must be a JSON object or null")
    if raw_content is not None and not isinstance(raw_content, dict):
        raise ValueError("payload.content must be a JSON object or null")
    if (
        isinstance(raw_content, dict)
        and legacy_html_body is not None
        and "html_body" not in raw_content
    ):
        raw_content = {**raw_content, "html_body": legacy_html_body}

    return IntakePayload(
        category=(
            NotificationCategory(str(data["category"]))
            if data.get("category") is not None
            else None
        ),
        topic=(
            _topic_from_json(data["topic"]) if data.get("topic") is not None else None
        ),
        channels=(
            tuple(
                DeliveryChannel(str(channel))
                for channel in _array(raw_channels, "payload.channels")
            )
            if raw_channels is not None
            else None
        ),
        adhoc_channels=(
            frozenset(
                DeliveryChannel(str(channel))
                for channel in _array(raw_adhoc_channels, "payload.adhoc_channels")
            )
            if raw_adhoc_channels is not None
            else None
        ),
        template_id=(
            _uuid(data["template_id"], "payload.template_id")
            if data.get("template_id") is not None
            else None
        ),
        template_slug=data.get("template_slug"),
        template_variables=raw_variables,
        content=(
            NotificationContent.from_dict(raw_content)
            if raw_content is not None
            else None
        ),
        group_key=data.get("group_key"),
        send_at=_optional_datetime(data.get("send_at"), "payload.send_at"),
    )


def _constraints_to_json(constraints: DecisionConstraints) -> JsonObject:
    """Serialize the worker's allowed decision space."""
    return {
        "allowed_categories": sorted(
            category.value for category in constraints.allowed_categories
        ),
        "default_category": constraints.default_category.value,
        "channel_mode": constraints.channel_mode,
        "feasible_channels": sorted(
            channel.value for channel in constraints.feasible_channels
        ),
        "max_channels": constraints.max_channels,
    }


def _constraints_from_json(value: object) -> DecisionConstraints:
    """Deserialize the worker's allowed decision space."""
    data = _object(value, "constraints")
    return DecisionConstraints(
        allowed_categories=frozenset(
            NotificationCategory(str(category))
            for category in _array(
                data.get("allowed_categories"), "constraints.allowed_categories"
            )
        ),
        default_category=NotificationCategory(str(data["default_category"])),
        channel_mode=data["channel_mode"],
        feasible_channels=frozenset(
            DeliveryChannel(str(channel))
            for channel in _array(
                data.get("feasible_channels"), "constraints.feasible_channels"
            )
        ),
        max_channels=int(data["max_channels"]),
    )


def _plan_to_json(plan: NotificationPlan) -> JsonObject:
    """Serialize the trusted worker decision."""
    return {
        "category": plan.category.value,
        "category_source": plan.category_source,
        "topic": _topic_to_json(plan.topic) if plan.topic else None,
        "topic_source": plan.topic_source,
        "channels": [channel.value for channel in plan.channels],
        "channel_source": plan.channel_source,
        "send_at": {
            channel.value: timestamp.isoformat()
            for channel, timestamp in plan.send_at.items()
        },
        "model_version": plan.model_version,
    }


def _plan_from_json(value: object) -> NotificationPlan:
    """Deserialize the trusted worker decision."""
    data = _object(value, "plan")
    raw_send_at = _object(data.get("send_at"), "plan.send_at")
    return NotificationPlan(
        category=NotificationCategory(str(data["category"])),
        category_source=data["category_source"],
        topic=(
            _topic_from_json(data["topic"]) if data.get("topic") is not None else None
        ),
        topic_source=data.get("topic_source"),
        channels=tuple(
            DeliveryChannel(str(channel))
            for channel in _array(data.get("channels"), "plan.channels")
        ),
        channel_source=data["channel_source"],
        send_at={
            DeliveryChannel(str(channel)): _datetime(
                timestamp, f"plan.send_at.{channel}"
            )
            for channel, timestamp in raw_send_at.items()
        },
        model_version=data.get("model_version"),
    )


class SQLAlchemyNotificationIntakeRepository(NotificationIntakeRepository):
    """SQLAlchemy implementation of the notification intake repository.

    The repository never commits or rolls back. The unit of work owns the
    transaction, while this adapter flushes state and translates between the
    domain aggregate and its PostgreSQL representation.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the request or worker session."""
        self._session = session

    async def add(self, intake: NotificationIntake) -> None:
        """Insert an intake, raising on a duplicate idempotency key.

        ``ON CONFLICT DO NOTHING`` is scoped to the partial idempotency index,
        so a duplicate key is handled without aborting the caller's transaction.
        Other constraints, including a duplicated primary key, still propagate.
        """
        statement = (
            pg_insert(NotificationIntakeModel)
            .values(**self._values(intake))
            .on_conflict_do_nothing(
                index_elements=[
                    NotificationIntakeModel.project_id,
                    NotificationIntakeModel.idempotency_key,
                ],
                index_where=NotificationIntakeModel.idempotency_key.is_not(None),
            )
            .returning(NotificationIntakeModel.id)
        )
        result = await self._session.execute(statement)
        if result.scalar_one_or_none() is None:
            raise IntakeAlreadyExistsError()

    async def get_by_transaction_id(
        self, transaction_id: UUID, project_id: UUID
    ) -> NotificationIntake | None:
        """Load an intake by its transaction identifier within a project."""
        result = await self._session.execute(
            select(NotificationIntakeModel)
            .where(NotificationIntakeModel.project_id == project_id)
            .where(NotificationIntakeModel.transaction_id == transaction_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_idempotency_key(
        self, project_id: UUID, idempotency_key: str
    ) -> NotificationIntake | None:
        """Load the intake associated with a project-scoped idempotency key."""
        result = await self._session.execute(
            select(NotificationIntakeModel)
            .where(NotificationIntakeModel.project_id == project_id)
            .where(NotificationIntakeModel.idempotency_key == idempotency_key)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_for_update(self, intake_id: UUID) -> NotificationIntake | None:
        """Load and lock an intake, skipping rows claimed by another worker."""
        result = await self._session.execute(
            select(NotificationIntakeModel)
            .where(NotificationIntakeModel.id == intake_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def save(self, intake: NotificationIntake) -> None:
        """Insert or update the intake with the same aggregate identifier."""
        await self._session.merge(self._to_model(intake))
        await self._session.flush()

    @staticmethod
    def _values(entity: NotificationIntake) -> JsonObject:
        """Build the PostgreSQL insert/update shape for an intake."""
        return {
            "id": entity.id,
            "project_id": entity.project_id,
            "transaction_id": entity.transaction_id,
            "recipient_id": entity.recipient_id,
            "request_fingerprint": entity.request_fingerprint,
            "idempotency_key": entity.idempotency_key,
            "payload": _payload_to_json(entity.payload),
            "constraints": _constraints_to_json(entity.constraints),
            "plan": _plan_to_json(entity.plan) if entity.plan else None,
            "status": entity.status.value,
            "attempts": entity.attempts,
            "claimed_at": entity.claimed_at,
            "completed_at": entity.completed_at,
            "failure_reason": entity.failure_reason,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }

    @classmethod
    def _to_model(cls, entity: NotificationIntake) -> NotificationIntakeModel:
        """Map a domain intake to an ORM model."""
        return NotificationIntakeModel(**cls._values(entity))

    @staticmethod
    def _to_entity(model: NotificationIntakeModel) -> NotificationIntake:
        """Map an ORM model back to a validated domain intake."""
        return NotificationIntake.reconstitute(
            id=model.id,
            project_id=model.project_id,
            transaction_id=model.transaction_id,
            recipient_id=model.recipient_id,
            payload=_payload_from_json(model.payload),
            constraints=_constraints_from_json(model.constraints),
            request_fingerprint=model.request_fingerprint,
            idempotency_key=model.idempotency_key,
            status=IntakeStatus(model.status),
            plan=_plan_from_json(model.plan) if model.plan is not None else None,
            attempts=model.attempts,
            claimed_at=model.claimed_at,
            completed_at=model.completed_at,
            failure_reason=model.failure_reason,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
