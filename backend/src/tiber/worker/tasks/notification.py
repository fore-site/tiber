"""Notification processing tasks."""

from celery.utils.log import get_task_logger

from ..celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    name="notification.process",
)
def process_notification(notification_id: str) -> None:
    """Notification processing task placeholder.

    This task will eventually become Tiber's Notification Processor.
    For now, it simply verifies that Celery can receive and execute tasks.
    """
    logger.info(f"Notification task received notification_id={notification_id}")
