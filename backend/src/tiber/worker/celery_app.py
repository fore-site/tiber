from celery import Celery

from ..core.config import get_settings
from .queues import NOTIFICATIONS_EXCHANGE, TASK_QUEUES
from .routing import task_routes

settings = get_settings()

# Create Celery instance
celery_app = Celery(
    "tiber",
    broker=settings.celery_broker_url,
)

celery_app.conf.update(
    # Broker settings
    broker_connection_retry_on_startup=True,
    broker_pool_limit=10,
    broker_heartbeat=30,
    # Task settings
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes=task_routes,
    # Task execution
    task_acks_late=True,  # Require explicit ack after task runs (safe for retries)
    task_queues=TASK_QUEUES,
    task_default_exchange=NOTIFICATIONS_EXCHANGE.name,
    task_default_routing_key="notification.created",
    task_reject_on_worker_lost=True,  # If worker dies, re-queue the message
    task_track_started=False,
    task_default_retry_delay=30,  # Default retry delay in seconds
    task_ignore_result=True,
    result_backend=None,
    worker_prefetch_multiplier=1,
    imports=("tiber.worker.tasks.notification"),
)
