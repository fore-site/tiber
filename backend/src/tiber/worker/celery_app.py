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
    broker_transport_options={"confirm_publish": True},
    # Task settings
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes=task_routes,
    # Task execution
    task_acks_late=True,  # Require explicit ack after task runs (safe for retries)
    # Let RabbitMQ reject exhausted task failures so the delivery queue's
    # dead-letter exchange receives them instead of Celery acknowledging them.
    task_acks_on_failure_or_timeout=False,
    task_queues=TASK_QUEUES,
    task_default_exchange=NOTIFICATIONS_EXCHANGE.name,
    # Routing is channel-aware: the publisher stamps each job with a
    # ``notification.{channel}`` key; this is only the fallback for the (rare)
    # case where no explicit routing key is supplied at publish time.
    task_default_routing_key="notification.email",
    task_reject_on_worker_lost=True,  # If worker dies, re-queue the message
    task_track_started=False,
    task_default_retry_delay=30,  # Default retry delay in seconds
    task_publish_retry=True,
    task_publish_retry_policy={
        "max_retries": 5,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 2,
    },
    task_default_delivery_mode=2,
    task_ignore_result=True,
    result_backend=None,
    worker_prefetch_multiplier=1,
    imports=(
        "tiber.worker.tasks.intake",
        "tiber.worker.tasks.notification",
        "tiber.worker.tasks.outbox",
    ),
    beat_schedule={
        "relay-transactional-outbox": {
            "task": "outbox.relay",
            "schedule": settings.outbox_relay_interval_seconds,
            "options": {
                "queue": "tiber.internal.queue",
                "routing_key": "internal.tasks",
            },
        }
    },
)
