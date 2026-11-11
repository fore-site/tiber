import logging
from typing import Any

from celery import Celery, _state
from celery.signals import beat_init, setup_logging

from ..core.config import get_settings
from ..core.logging import configure_logging
from .queues import NOTIFICATIONS_EXCHANGE, TASK_QUEUES
from .routing import task_routes

settings = get_settings()


def _transaction_id_from(request: Any) -> str | None:
    """Return the transaction this message was published for, if it carries one.

    ``notification.process`` puts it inside the job payload;
    ``notification.intake`` receives it as a keyword argument. Messages
    published without it (in flight during a deploy, or ``outbox.relay``,
    which spans many transactions) return ``None`` rather than guessing, since
    recovering it would need a database read.
    """
    args = getattr(request, "args", None) or ()
    if args:
        job = args[0]
        if hasattr(job, "model_dump"):
            job = job.model_dump(mode="json")
        if isinstance(job, dict) and job.get("transaction_id"):
            return str(job["transaction_id"])

    transaction_id = (getattr(request, "kwargs", None) or {}).get("transaction_id")
    return str(transaction_id) if transaction_id else None


def _add_task_context(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Attach the running task's id and the business ids it carries.

    ``task_id`` identifies one message and stays fixed across retries and
    deferrals, so it separates concurrent runs of the same job. The
    ``transaction_id`` taken from the job payload identifies the client
    request instead: it is the same for every channel's job, survives
    republication from the outbox, and is what the API stores and returns.

    Both are read from Celery's task stack rather than bound as contextvars on
    purpose: ``async_runtime`` reuses a single ``asyncio.Runner``, whose
    ``Context`` is captured once on first use, so per-task contextvar bindings
    would leak the first task's values into every later one.
    """
    request = getattr(_state.get_current_task(), "request", None)
    if request is None:
        return event_dict

    task_id = getattr(request, "id", None)
    if task_id is not None:
        event_dict.setdefault("task_id", task_id)

    transaction_id = _transaction_id_from(request)
    if transaction_id is not None:
        event_dict.setdefault("transaction_id", transaction_id)

    return event_dict


@setup_logging.connect(weak=False)
def _configure_worker_logging(**_: object) -> None:
    """Install structlog for the worker and beat processes.

    Celery only configures logging when this signal has no receivers, so
    connecting it replaces Celery's formatter rather than layering on top of
    it: the ``celery``, ``celery.task`` and task-module loggers keep
    ``propagate = True`` and reach the single root handler installed here.

    Celery's ``--loglevel`` flag is ignored on purpose; the level follows
    ``settings.debug``, like the API. This runs in the worker's main process
    before the pool forks, so pool children inherit the handler.
    """
    configure_logging(extra_processors=[_add_task_context])


@beat_init.connect(weak=False)
def _quiet_beat_logger(**_: object) -> None:
    """Hold beat's scheduler at WARNING; the worker keeps structlog's level."""
    logging.getLogger("celery.beat").setLevel(logging.WARNING)


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
