from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ..application.ports.intake import Outbox
from ..application.ports.unit_of_work import UnitOfWork
from ..application.services.notification_intake import NotificationIntakeService
from ..application.services.notification_query import NotificationQueryService
from ..application.services.recipient_resolution import RecipientResolutionService
from ..core.config import get_settings
from ..core.database import AsyncSessionFactory
from ..core.redis import get_redis_client
from ..domain.repositories import NotificationIntakeRepository
from ..infrastructure.messaging.sqlalchemy_outbox import SQLAlchemyOutbox
from ..infrastructure.models import ProjectModel
from ..infrastructure.rate_limit.ingestion_rate_limiter import IngestionRateLimiter
from ..infrastructure.repositories.sqlalchemy_notification_intake_repository import (
    SQLAlchemyNotificationIntakeRepository,
)
from ..infrastructure.repositories.sqlalchemy_notification_repository import (
    SQLAlchemyNotificationRepository,
)
from ..infrastructure.repositories.sqlalchemy_notification_topic_repository import (
    SQLAlchemyNotificationTopicRepository,
)
from ..infrastructure.repositories.sqlalchemy_recipient_repository import (
    SQLAlchemyRecipientRepository,
)
from ..infrastructure.repositories.sqlalchemy_template_repository import (
    SQLAlchemyTemplateRepository,
)

# Written below as stubs of names; these modules do not exist yet.
from ..infrastructure.unit_of_work import SqlAlchemyUnitOfWork

settings = get_settings()


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Yield one AsyncSession per request; always close it.

    This does NOT commit. Commits belong to the UnitOfWork, so a write that
    happens outside ``async with uow:`` is rolled back on close instead of being
    committed silently. Every repository and the UnitOfWork resolve this same
    session, because FastAPI caches a dependency per request.

    Use as: db: AsyncSession = Depends(get_db).
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_redis() -> AsyncGenerator[Redis]:
    """Yield a Redis client per request.

    Use as: redis: Redis = Depends(get_redis)
    """
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()


async def get_authenticated_project(
    project_id: UUID,
    authorization: Annotated[str | None, Header(alias="Authorization")],
) -> ProjectModel:
    """Resolve the project targeted by a request.

    NOTE: Full API-key verification is Phase 7 work. For now the path
    ``project_id`` is trusted (after a minimal Bearer-header presence check)
    so the core notification flow is exercisable; this MUST be replaced with
    real key verification before any production use.
    """
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
        )

    scheme, _, credential = authorization.partition(" ")

    if scheme.lower() != "bearer" or not credential:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header.",
        )

    async with AsyncSessionFactory() as session:
        project = await session.get(ProjectModel, project_id)

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    return project


# Infrastructure bound to the request session


def get_unit_of_work(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UnitOfWork:
    """Provide the unit of work over the request session."""
    return SqlAlchemyUnitOfWork(db)


def get_notification_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SQLAlchemyNotificationRepository:
    """Provide the SQLAlchemy notification repository bound to the request session."""
    return SQLAlchemyNotificationRepository(db)


def get_recipient_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SQLAlchemyRecipientRepository:
    """Provide the SQLAlchemy recipient repository bound to the request session."""
    return SQLAlchemyRecipientRepository(db)


def get_template_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SQLAlchemyTemplateRepository:
    """Provide the SQLAlchemy template repository bound to the request session."""
    return SQLAlchemyTemplateRepository(db)


def get_intake_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationIntakeRepository:
    """Provide the SQLAlchemy intake repository bound to the request session."""
    return SQLAlchemyNotificationIntakeRepository(db)


def get_outbox(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Outbox:
    """Provide the transactional outbox (writes in the request transaction)."""
    return SQLAlchemyOutbox(db)


def get_topic_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SQLAlchemyNotificationTopicRepository:
    """Provide the SQLAlchemy topic repository bound to the request session."""
    return SQLAlchemyNotificationTopicRepository(db)


def get_ingestion_rate_limiter(
    redis: Annotated[Redis, Depends(get_redis)],
) -> IngestionRateLimiter:
    """Provide the Redis-backed ingestion rate limiter for POST /notifications."""
    return IngestionRateLimiter(
        redis,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )


# --------------------------------------------------------------------------- #
# Application services
# --------------------------------------------------------------------------- #


def get_recipient_resolution_service(
    recipient_repository: Annotated[
        SQLAlchemyRecipientRepository, Depends(get_recipient_repository)
    ],
) -> RecipientResolutionService:
    """Provide registered-recipient lookup and ad-hoc recipient matching."""
    return RecipientResolutionService(recipient_repository=recipient_repository)


def get_notification_intake_service(
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    intake_repository: Annotated[
        NotificationIntakeRepository, Depends(get_intake_repository)
    ],
    outbox: Annotated[Outbox, Depends(get_outbox)],
    recipient_resolution: Annotated[
        RecipientResolutionService, Depends(get_recipient_resolution_service)
    ],
    template_repository: Annotated[
        SQLAlchemyTemplateRepository, Depends(get_template_repository)
    ],
    topic_repository: Annotated[
        SQLAlchemyNotificationTopicRepository, Depends(get_topic_repository)
    ],
) -> NotificationIntakeService:
    """Provide the synchronous accept path (validate, persist intake, enqueue)."""
    return NotificationIntakeService(
        unit_of_work=unit_of_work,
        intake_repository=intake_repository,
        outbox=outbox,
        recipient_resolution=recipient_resolution,
        template_repository=template_repository,
        topic_repository=topic_repository,
    )


def get_notification_query_service(
    notification_repository: Annotated[
        SQLAlchemyNotificationRepository, Depends(get_notification_repository)
    ],
    intake_repository: Annotated[
        NotificationIntakeRepository, Depends(get_intake_repository)
    ],
    recipient_repository: Annotated[
        SQLAlchemyRecipientRepository, Depends(get_recipient_repository)
    ],
) -> NotificationQueryService:
    """Provide the read side of notifications."""
    return NotificationQueryService(
        notification_repository=notification_repository,
        intake_repository=intake_repository,
        recipient_repository=recipient_repository,
    )


# Moved out of the API process (they now belong to the worker's IntakeProcessor
# wiring): idempotency guard, message publisher, template resolver, policy
# resolver, channel ranker/resolver, delivery constraint repository.
