from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tiber.domain.entities.notification_intake import NotificationIntake
from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.domain.exceptions import IntakeAlreadyExistsError
from tiber.domain.value_objects import NotificationContent
from tiber.domain.value_objects.intake import DecisionConstraints, IntakePayload
from tiber.infrastructure.models import AccountModel, ProjectModel, RecipientModel
from tiber.infrastructure.repositories.sqlalchemy_notification_intake_repository import (
    SQLAlchemyNotificationIntakeRepository,
)


@pytest.mark.asyncio
async def test_notification_intake_persists_and_enforces_project_idempotency(
    integration_session: AsyncSession,
) -> None:
    """The PostgreSQL adapter stores an intake and rejects a reused project key."""
    session = integration_session
    account = AccountModel(email=f"{uuid4().hex}@example.com")
    session.add(account)
    await session.flush()

    project = ProjectModel(
        account_id=account.id,
        name="Integration",
        slug=f"integration-{uuid4().hex}",
    )
    session.add(project)
    await session.flush()

    recipient = RecipientModel(
        project_id=project.id,
        addresses={"email": "integration@example.com"},
    )
    session.add(recipient)
    await session.commit()

    payload = IntakePayload(
        category=NotificationCategory.INFORMATIONAL,
        channels=(DeliveryChannel.EMAIL,),
        content=NotificationContent(title="Status", plain_text_body="Integration test"),
    )
    constraints = DecisionConstraints(
        allowed_categories=frozenset({NotificationCategory.INFORMATIONAL}),
        default_category=NotificationCategory.INFORMATIONAL,
        channel_mode="client",
        feasible_channels=frozenset({DeliveryChannel.EMAIL}),
        max_channels=1,
    )
    intake = NotificationIntake.create(
        project_id=project.id,
        recipient_id=recipient.id,
        payload=payload,
        constraints=constraints,
        request_fingerprint="integration-fingerprint",
        idempotency_key="same-key",
    )
    repository = SQLAlchemyNotificationIntakeRepository(session)

    await repository.add(intake)
    await session.commit()

    restored = await repository.get_by_transaction_id(intake.transaction_id, project.id)
    assert restored == intake
    assert await repository.get_by_idempotency_key(project.id, "same-key") == intake

    duplicate = NotificationIntake.create(
        project_id=project.id,
        recipient_id=recipient.id,
        payload=payload,
        constraints=constraints,
        request_fingerprint="different-fingerprint",
        idempotency_key="same-key",
    )
    with pytest.raises(IntakeAlreadyExistsError):
        await repository.add(duplicate)

    assert (
        await repository.get_by_transaction_id(intake.transaction_id, project.id)
    ) == intake
