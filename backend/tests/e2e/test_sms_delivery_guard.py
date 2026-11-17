"""Worker-side guard for notifications queued before SMS was disabled."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from tiber.domain.entities import Notification
from tiber.domain.enums import (
    DeliveryChannel,
    NotificationCategory,
    SendTimeBasis,
)
from tiber.domain.exceptions import ChannelNotAvailableError
from tiber.domain.value_objects import NotificationContent
from tiber.infrastructure.models import RecipientModel
from tiber.infrastructure.repositories.sqlalchemy_notification_repository import (
    SQLAlchemyNotificationRepository,
)
from tiber.infrastructure.repositories.unit_of_work import SqlAlchemyUnitOfWork
from tiber.worker.tasks import notification as notification_task

pytestmark = pytest.mark.e2e


async def test_worker_refuses_a_queued_sms_notification(
    db_engine,
    project,
    session,
) -> None:
    """A pre-existing SMS job fails instead of reaching the provider."""
    recipient = RecipientModel(
        project_id=project.id,
        addresses={"sms": "+15551234567"},
    )
    session.add(recipient)
    await session.commit()

    notification = Notification.create(
        project_id=project.id,
        recipient_id=recipient.id,
        transaction_id=uuid4(),
        channel=DeliveryChannel.SMS,
        category=NotificationCategory.INFORMATIONAL,
        content=NotificationContent(plain_text_body="Hello"),
        send_at=datetime.now(UTC),
        send_time_basis=SendTimeBasis.EXPLICIT,
    )
    async with SqlAlchemyUnitOfWork(session):
        await SQLAlchemyNotificationRepository(session).save(notification)

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    with (
        patch.object(notification_task, "AsyncSessionFactory", factory),
        pytest.raises(ChannelNotAvailableError, match="SMS delivery is coming soon"),
    ):
        await notification_task._process(notification.id, project.id)
