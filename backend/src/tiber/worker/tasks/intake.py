"""Celery task for expanding accepted notification intakes."""

from __future__ import annotations

from uuid import UUID

from celery.utils.log import get_task_logger

from ...application.services.intake_processor import IntakeProcessor
from ...application.services.template import NotificationTemplateResolver
from ...core.database import AsyncSessionFactory
from ...domain.policies import PolicyResolver
from ...infrastructure.ai.fallback import FallbackDecisionEngine
from ...infrastructure.repositories.sqlalchemy_brand_profile_repository import (
    SQLAlchemyBrandProfileRepository,
)
from ...infrastructure.repositories.sqlalchemy_delivery_constraint_repository import (
    SQLAlchemyDeliveryConstraintRepository,
)
from ...infrastructure.repositories.sqlalchemy_notification_intake_repository import (
    SQLAlchemyNotificationIntakeRepository,
)
from ...infrastructure.repositories.sqlalchemy_notification_repository import (
    SQLAlchemyNotificationRepository,
)
from ...infrastructure.repositories.sqlalchemy_notification_topic_repository import (
    SQLAlchemyNotificationTopicRepository,
)
from ...infrastructure.repositories.sqlalchemy_outbox import SQLAlchemyOutbox
from ...infrastructure.repositories.sqlalchemy_recipient_repository import (
    SQLAlchemyRecipientRepository,
)
from ...infrastructure.repositories.sqlalchemy_template_repository import (
    SQLAlchemyTemplateRepository,
)
from ...infrastructure.repositories.unit_of_work import SqlAlchemyUnitOfWork
from ..async_runtime import run_async
from ..celery_app import celery_app

logger = get_task_logger(__name__)


async def _process(intake_id: UUID) -> None:
    """Compose the intake use case with worker-scoped repositories."""
    async with AsyncSessionFactory() as session:
        intake_repository = SQLAlchemyNotificationIntakeRepository(session)
        notification_repository = SQLAlchemyNotificationRepository(session)
        recipient_repository = SQLAlchemyRecipientRepository(session)
        template_repository = SQLAlchemyTemplateRepository(session)
        service = IntakeProcessor(
            unit_of_work=SqlAlchemyUnitOfWork(session),
            intake_repository=intake_repository,
            notification_repository=notification_repository,
            recipient_repository=recipient_repository,
            topic_repository=SQLAlchemyNotificationTopicRepository(session),
            template_resolver=NotificationTemplateResolver(
                template_repository,
                brand_profile_repository=SQLAlchemyBrandProfileRepository(session),
            ),
            policy_resolver=PolicyResolver(),
            decision_engine=FallbackDecisionEngine(),
            outbox=SQLAlchemyOutbox(session),
            constraint_repository=SQLAlchemyDeliveryConstraintRepository(session),
        )
        await service.process(intake_id)


@celery_app.task(
    name="notification.intake",
    bind=True,
    max_retries=5,
    default_retry_delay=30,
)
def process_notification_intake(self, intake_id: str) -> None:
    """Expand one accepted intake; retry infrastructure failures."""
    parsed_id = UUID(intake_id)
    try:
        run_async(_process(parsed_id))
    except Exception as exc:
        logger.exception("Intake processing failed intake_id=%s", parsed_id)
        raise self.retry(exc=exc, countdown=30, max_retries=5) from exc
