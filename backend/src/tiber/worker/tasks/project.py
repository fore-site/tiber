"""Celery task that hard-deletes projects after their 90-day grace period."""

from __future__ import annotations

from celery.utils.log import get_task_logger

from ...application.services.project_management import ProjectManagementService
from ...core.config import get_settings
from ...core.database import AsyncSessionFactory
from ...infrastructure.repositories.sqlalchemy_project_repository import (
    SQLAlchemyProjectRepository,
)
from ...infrastructure.repositories.unit_of_work import SqlAlchemyUnitOfWork
from ..async_runtime import run_async
from ..celery_app import celery_app

logger = get_task_logger(__name__)
settings = get_settings()


async def _purge_expired() -> int:
    """Drain expired projects in bounded batches on one session."""
    total = 0
    async with AsyncSessionFactory() as session:
        service = ProjectManagementService(
            unit_of_work=SqlAlchemyUnitOfWork(session),
            project_repository=SQLAlchemyProjectRepository(session),
        )
        while True:
            purged = await service.purge_expired(
                limit=settings.project_purge_batch_size
            )
            total += purged
            if purged < settings.project_purge_batch_size:
                return total


@celery_app.task(name="project.purge_expired")
def purge_expired_projects() -> int:
    """Permanently remove projects whose deletion grace period has elapsed."""
    purged = run_async(_purge_expired())
    if purged:
        logger.info("Purged %s expired projects", purged)
    return purged
