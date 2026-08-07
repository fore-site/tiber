from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ..application.ports.idempotency import IdempotencyGuard
from ..application.ports.message_publisher import MessagePublisher
from ..application.services import (
    NotificationService,
    NotificationTemplateResolver,
    PolicyResolver,
)
from ..core.config import get_settings
from ..core.database import AsyncSessionFactory
from ..core.redis import get_redis_client
from ..infrastructure.cache.idempotency import IdempotencyStore
from ..infrastructure.messaging.celery_publisher import CeleryPublisher
from ..infrastructure.models import ProjectModel
from ..infrastructure.rate_limit.ingestion_rate_limiter import IngestionRateLimiter
from ..infrastructure.repositories.sqlalchemy_notification_repository import (
    SQLAlchemyNotificationRepository,
)
from ..infrastructure.repositories.sqlalchemy_recipient_repository import (
    SQLAlchemyRecipientRepository,
)
from ..infrastructure.repositories.sqlalchemy_template_repository import (
    SQLAlchemyTemplateRepository,
)

settings = get_settings()


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Yield an AsyncSession per request, roll back on error, always close.

    Use as: db: AsyncSession = Depends(get_db).
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
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


def get_idempotency_guard(
    redis: Annotated[Redis, Depends(get_redis)],
) -> IdempotencyGuard:
    """Provide the Redis-backed idempotency guard."""
    return IdempotencyStore(redis)


def get_notification_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SQLAlchemyNotificationRepository:
    """Provide the SQLAlchemy notification repository bound to the request session."""
    return SQLAlchemyNotificationRepository(db)


def get_message_publisher() -> MessagePublisher:
    """Provide the Celery message publisher."""
    return CeleryPublisher()


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


def get_template_resolver(
    template_repository: Annotated[
        SQLAlchemyTemplateRepository, Depends(get_template_repository)
    ],
) -> NotificationTemplateResolver:
    """Provide the intake-time template resolver (validates + renders)."""
    return NotificationTemplateResolver(template_repository=template_repository)


def get_policy_resolver() -> PolicyResolver:
    """Provide the intake-time delivery policy resolver (permissive default)."""
    return PolicyResolver()


def get_ingestion_rate_limiter(
    redis: Annotated[Redis, Depends(get_redis)],
) -> IngestionRateLimiter:
    """Provide the Redis-backed ingestion rate limiter for POST /notifications."""
    return IngestionRateLimiter(
        redis,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )


def get_notification_service(
    idempotency_guard: Annotated[IdempotencyGuard, Depends(get_idempotency_guard)],
    repository: Annotated[
        SQLAlchemyNotificationRepository, Depends(get_notification_repository)
    ],
    publisher: Annotated[MessagePublisher, Depends(get_message_publisher)],
    recipient_repository: Annotated[
        SQLAlchemyRecipientRepository, Depends(get_recipient_repository)
    ],
    template_resolver: Annotated[
        NotificationTemplateResolver, Depends(get_template_resolver)
    ],
    policy_resolver: Annotated[PolicyResolver, Depends(get_policy_resolver)],
) -> NotificationService:
    """Provide the notification application service."""
    return NotificationService(
        idempotency_guard=idempotency_guard,
        repository=repository,
        publisher=publisher,
        recipient_repository=recipient_repository,
        template_resolver=template_resolver,
        policy_resolver=policy_resolver,
    )
