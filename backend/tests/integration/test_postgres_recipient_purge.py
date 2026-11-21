from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tiber.application.services.recipient_management import RECIPIENT_PURGE_GRACE_PERIOD
from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.infrastructure.models import (
    AccountModel,
    NotificationModel,
    ProjectModel,
    RecipientModel,
)
from tiber.infrastructure.repositories.sqlalchemy_recipient_repository import (
    SQLAlchemyRecipientRepository,
)


@pytest.mark.asyncio
async def test_purge_removes_expired_tombstones_and_detaches_history(
    integration_session: AsyncSession,
) -> None:
    """One batch deletes only old tombstones; their notifications survive."""
    session = integration_session
    account = AccountModel(email=f"{uuid4().hex}@example.com")
    session.add(account)
    await session.flush()

    project = ProjectModel(
        account_id=account.id,
        name="Purge",
        slug=f"purge-{uuid4().hex}",
    )
    session.add(project)
    await session.flush()

    cutoff = datetime.now(UTC) - RECIPIENT_PURGE_GRACE_PERIOD

    # A tombstone is identity-less by construction: delete() scrubs it. Only
    # consent state remains until the purge removes the row.
    expired = RecipientModel(
        project_id=project.id,
        external_id=None,
        addresses={},
        preferences={"opted_out_channels": ["email"]},
        deleted_at=cutoff - timedelta(hours=1),
    )
    recent = RecipientModel(
        project_id=project.id,
        external_id=None,
        addresses={},
        deleted_at=cutoff + timedelta(hours=1),
    )
    live = RecipientModel(
        project_id=project.id,
        external_id="still-here",
        addresses={"email": "live@example.com"},
    )
    session.add_all([expired, recent, live])
    await session.flush()

    notification = NotificationModel(
        project_id=project.id,
        recipient_id=expired.id,
        channel=DeliveryChannel.IN_APP,
        category=NotificationCategory.INFORMATIONAL,
        transaction_id=uuid4(),
        body="Delivered before the recipient was erased.",
    )
    session.add(notification)
    await session.commit()

    repository = SQLAlchemyRecipientRepository(session)
    removed = await repository.purge_expired(cutoff, limit=10)
    await session.commit()

    assert removed == 1
    remaining = set((await session.scalars(select(RecipientModel.id))).all())
    assert remaining == {recent.id, live.id}

    # The history row keeps its content and loses only the pointer, which is the
    # ON DELETE SET NULL the migration installed.
    await session.refresh(notification)
    assert notification.recipient_id is None
    assert notification.body == "Delivered before the recipient was erased."


@pytest.mark.asyncio
async def test_purge_batch_is_bounded_by_the_limit(
    integration_session: AsyncSession,
) -> None:
    """A backlog is drained in batches, oldest deletion first."""
    session = integration_session
    account = AccountModel(email=f"{uuid4().hex}@example.com")
    session.add(account)
    await session.flush()

    project = ProjectModel(
        account_id=account.id,
        name="Purge batch",
        slug=f"purge-batch-{uuid4().hex}",
    )
    session.add(project)
    await session.flush()

    cutoff = datetime.now(UTC) - RECIPIENT_PURGE_GRACE_PERIOD
    tombstones = [
        RecipientModel(
            project_id=project.id,
            external_id=None,
            addresses={},
            deleted_at=cutoff - timedelta(days=index + 1),
        )
        for index in range(3)
    ]
    session.add_all(tombstones)
    await session.commit()

    repository = SQLAlchemyRecipientRepository(session)
    first = await repository.purge_expired(cutoff, limit=2)
    await session.commit()
    second = await repository.purge_expired(cutoff, limit=2)
    await session.commit()

    assert (first, second) == (2, 1)
    assert (await session.scalars(select(RecipientModel.id))).all() == []
