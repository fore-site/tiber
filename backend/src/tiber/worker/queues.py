"""Channel-aware RabbitMQ topology: per-channel delivery queues and DLQs.

Retry *delays* are handled natively by Celery (``self.retry`` with an
exponential-backoff ``countdown``), so workers never block while a job waits to
be retried - the functional equivalent of the broker-managed retry queues
described in ``docs/architecture/07-rabbitmq-topology.md`` (same outcome: no
blocking workers, bounded retries). Once a job exhausts its bounded retry budget
the worker rejects/does not ack the message, so RabbitMQ dead-letters it to the
channel's DLQ via the ``x-dead-letter-exchange`` / ``x-dead-letter-routing-key``
arguments declared below. Failed deliveries are therefore never dropped - they
are preserved per-channel for inspection, replay, or archival.
"""

from __future__ import annotations

from kombu import Exchange, Queue

from ..domain.enums import DeliveryChannel

NOTIFICATIONS_EXCHANGE = Exchange(
    "notifications.exchange",
    type="topic",
    durable=True,
)

# Exhausted jobs are dead-lettered to a per-channel DLQ via this exchange.
DLQ_EXCHANGE = Exchange(
    "notifications.dlq.exchange",
    type="topic",
    durable=True,
)


def channel_topology(channel: DeliveryChannel) -> tuple[Queue, Queue]:
    """Return ``(delivery_queue, dead_letter_queue)`` for a channel.

    The delivery queue declares a dead-letter exchange so RabbitMQ routes a
    rejected/exhausted message to the channel's DLQ instead of dropping it. The
    DLQ is a durable, channel-scoped queue bound to the DLQ exchange.
    """
    name = channel.value
    delivery = Queue(
        f"{name}.delivery.queue",
        exchange=NOTIFICATIONS_EXCHANGE,
        routing_key=f"notification.{name}",
        durable=True,
        queue_arguments={
            "x-dead-letter-exchange": DLQ_EXCHANGE.name,
            "x-dead-letter-routing-key": f"{name}.dlq",
        },
    )
    dlq = Queue(
        f"{name}.dlq",
        exchange=DLQ_EXCHANGE,
        routing_key=f"{name}.dlq",
        durable=True,
    )
    return delivery, dlq


_CHANNELS: tuple[DeliveryChannel, ...] = tuple(DeliveryChannel)

DELIVERY_QUEUES: tuple[Queue, ...] = tuple(
    channel_topology(channel)[0] for channel in _CHANNELS
)
DLQS: tuple[Queue, ...] = tuple(channel_topology(channel)[1] for channel in _CHANNELS)

#: Queues Celery must declare on connect: every channel delivery queue and DLQ.
TASK_QUEUES: tuple[Queue, ...] = DELIVERY_QUEUES + DLQS
