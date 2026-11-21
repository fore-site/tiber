"""Celery task that removes recipient tombstones after their grace period."""

from __future__ import annotations

from celery.utils.log import get_task_logger

from ...application.services.recipient_management import RecipientManagementService
from ...core.config import get_settings
from ...core.database import AsyncSessionFactory
from ...infrastructure.repositories.sqlalchemy_recipient_repository import (
    SQLAlchemyRecipientRepository,
)
from ...infrastructure.repositories.unit_of_work import SqlAlchemyUnitOfWork
from ..async_runtime import run_async
from ..celery_app import celery_app

logger = get_task_logger(__name__)
settings = get_settings()


async def _purge_expired() -> int:
    """Drain expired tombstones in bounded batches on one session.

    Each batch is its own transaction (the service opens the unit of work), so a
    large backlog cannot hold one transaction open until every row is gone. The
    loop stops on a short batch rather than re-querying after it: that is the
    same signal the project purger uses, and a row that fails to delete is a
    failure to report, not something to retry through silently.
    """
    total = 0
    async with AsyncSessionFactory() as session:
        service = RecipientManagementService(
            unit_of_work=SqlAlchemyUnitOfWork(session),
            recipient_repository=SQLAlchemyRecipientRepository(session),
        )
        while True:
            purged = await service.purge_expired(
                limit=settings.recipient_purge_batch_size
            )
            total += purged
            if purged < settings.recipient_purge_batch_size:
                return total


@celery_app.task(name="recipient.purge_expired")
def purge_expired_recipients() -> int:
    """Permanently remove recipients deleted more than the grace period ago.

    Their personal data was already scrubbed by the delete itself; this removes
    the tombstone (and its stored consent state) once the row is no longer needed
    to attribute history.
    """
    purged = run_async(_purge_expired())
    if purged:
        logger.info("Purged %s expired recipients", purged)
    return purged
