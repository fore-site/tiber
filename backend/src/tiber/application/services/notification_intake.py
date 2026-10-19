"""Synchronous half of notification creation: validate, persist an intake, return.

Everything a client can act on is checked here, so the worker never has to
reject anything the client caused:

    idempotency lookup            -> replay, or 409 if the payload differs
    template / topic slugs        -> 422 if unknown
    recipient resolution          -> 404 / 409 (ambiguous or conflicting addresses)
    template variables, channels  -> 422 (via ``compute_constraints``)
    intake + outbox row           -> one transaction

No ML runs here. Open decisions (category, topic, channels, send time) are left
to ``IntakeProcessor`` and are constrained by what was validated here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from tiber.application.ports.intake import Outbox
from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.application.services.recipient_resolution import RecipientResolutionService
from tiber.domain.entities import NotificationTopic, Template
from tiber.domain.entities.notification_intake import NotificationIntake
from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.domain.exceptions import (
    EntityNotFoundError,
    IdempotencyKeyConflictError,
    IntakeAlreadyExistsError,
    InvalidEntityAttributeError,
)
from tiber.domain.repositories import (
    NotificationIntakeRepository,
    NotificationTopicRepository,
    TemplateRepository,
)
from tiber.domain.services.addresses import normalize_address
from tiber.domain.services.decision_constraints import compute_constraints
from tiber.domain.value_objects import NotificationContent
from tiber.domain.value_objects.intake import IntakePayload, ResolvedTopic, TemplateInfo


@dataclass(frozen=True)
class AcceptNotificationCommand:
    """Command to accept a notification from the api."""

    project_id: UUID
    recipient_id: str | None
    addresses: Mapping[DeliveryChannel, str]  # only the channels the request supplied
    channels: Sequence[DeliveryChannel] | None
    category: NotificationCategory | None  # None -> ML infers
    topic_slug: str | None  # None -> ML infers
    template_slug: str | None
    template_variables: dict[str, Any] | None
    content: NotificationContent | None
    group_key: str | None
    send_at: datetime | None
    idempotency_key: str | None


@dataclass(frozen=True)
class AcceptedIntake:
    """Unique identifiers for an accepted notification intake."""

    correlation_id: UUID
    project_id: UUID
    replayed: bool = False


class NotificationIntakeService:
    """Accept and Process notification at the api layer."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        intake_repository: NotificationIntakeRepository,
        outbox: Outbox,
        recipient_resolution: RecipientResolutionService,
        template_repository: TemplateRepository,
        topic_repository: NotificationTopicRepository,
    ) -> None:
        """Initialize variables."""
        self._uow = unit_of_work
        self._intakes = intake_repository
        self._outbox = outbox
        self._recipients = recipient_resolution
        self._templates = template_repository
        self._topics = topic_repository

    async def accept(self, cmd: AcceptNotificationCommand) -> AcceptedIntake:
        """Accept the notification intake."""
        fingerprint = request_fingerprint(cmd)

        async with self._uow:
            replay = await self._replay(cmd, fingerprint)
            if replay is not None:
                return replay

            topic = await self._require_topic(cmd)
            template = await self._require_template(cmd)

            recipient = await self._recipients.resolve(
                project_id=cmd.project_id,
                recipient_id=cmd.recipient_id,
                addresses=cmd.addresses,
            )
            adhoc = cmd.recipient_id is None

            constraints = compute_constraints(
                # Address-based: the request defines the set, not whatever a
                # matched recipient has accumulated over time.
                available_channels=(
                    frozenset(cmd.addresses)
                    if adhoc
                    else frozenset(recipient.addresses)
                ),
                adhoc=adhoc,
                requested_channels=cmd.channels,
                opted_out=frozenset(recipient.preferences.opted_out_channels),
                client_category=cmd.category,
                template=template,
                template_variables=cmd.template_variables,
                content=cmd.content,
            )

            payload = IntakePayload(
                category=cmd.category,
                topic=topic,
                channels=tuple(cmd.channels) if cmd.channels else None,
                adhoc_channels=frozenset(cmd.addresses) if adhoc else None,
                template_id=template.id if template else None,
                template_slug=template.slug if template else None,
                template_variables=cmd.template_variables,
                content=cmd.content,
                group_key=cmd.group_key,
                send_at=cmd.send_at,
            )
            intake = NotificationIntake.create(
                project_id=cmd.project_id,
                recipient_id=recipient.id,
                payload=payload,
                constraints=constraints,
                request_fingerprint=fingerprint,
                idempotency_key=cmd.idempotency_key,
            )

            try:
                await self._intakes.add(intake)
            except IntakeAlreadyExistsError:
                # Lost a race with an identical request: replay the winner.
                replay = await self._replay(cmd, fingerprint)
                if replay is None:
                    raise
                return replay

            # Critical requests jump the queue (OTPs must not wait behind bulk sends).
            await self._outbox.enqueue_intake(
                intake,
                priority="high"
                if cmd.category is NotificationCategory.CRITICAL
                else "normal",
            )

        # Reached only after the transaction committed.
        return AcceptedIntake(intake.correlation_id, intake.project_id)

    async def _replay(
        self, cmd: AcceptNotificationCommand, fingerprint: str
    ) -> AcceptedIntake | None:
        if cmd.idempotency_key is None:
            return None
        existing = await self._intakes.get_by_idempotency_key(
            cmd.project_id, cmd.idempotency_key
        )
        if existing is None:
            return None
        if existing.request_fingerprint != fingerprint:
            raise IdempotencyKeyConflictError()
        return AcceptedIntake(
            existing.correlation_id, existing.project_id, replayed=True
        )

    async def _require_topic(
        self, cmd: AcceptNotificationCommand
    ) -> ResolvedTopic | None:
        if cmd.topic_slug is None:
            return None
        topic = await self._topics.get_by_slug(cmd.topic_slug, cmd.project_id)
        if topic is None:
            raise EntityNotFoundError(NotificationTopic, cmd.topic_slug)
        if topic.topic_slug is None:
            raise InvalidEntityAttributeError("Topic has no slug")
        # The payload stores id + slug, never the entity: the accept path only
        # needs something to reference at fan-out time.
        return ResolvedTopic(id=topic.id, slug=topic.topic_slug)

    async def _require_template(
        self, cmd: AcceptNotificationCommand
    ) -> TemplateInfo | None:
        if cmd.template_slug is None:
            return None
        template = await self._templates.get_by_slug(cmd.template_slug, cmd.project_id)
        if template is None:
            raise EntityNotFoundError(Template, cmd.template_slug)
        # Project the aggregate onto the fields constraints need. The intake
        # stores the id, so later renames cannot retarget accepted work.
        return TemplateInfo.from_template(template)


def request_fingerprint(cmd: AcceptNotificationCommand) -> str:
    """Stable hash of the request.

    A reused idempotency key with a different payload is rejected instead of silently returning the old result.

    Addresses are normalized and channel order is ignored (it carries no meaning).
    """
    document = {
        "recipient_id": cmd.recipient_id,
        "addresses": {
            ch.value: normalize_address(ch, v) for ch, v in cmd.addresses.items()
        },
        "channels": sorted(c.value for c in cmd.channels)
        if cmd.channels is not None
        else None,
        "category": cmd.category.value if cmd.category else None,
        "topic_slug": cmd.topic_slug,
        "template_slug": cmd.template_slug,
        "template_variables": cmd.template_variables,
        "content": cmd.content.to_dict() if cmd.content else None,
        "group_key": cmd.group_key,
        "send_at": cmd.send_at.astimezone(UTC).isoformat() if cmd.send_at else None,
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()
