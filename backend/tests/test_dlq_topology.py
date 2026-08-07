"""Unit tests for the channel-aware DLQ topology.

These assert the declarative RabbitMQ configuration (kombu Queue objects and
their dead-lettering arguments) without requiring a running broker.
"""

from __future__ import annotations

from kombu import Queue

from tiber.domain.enums import DeliveryChannel
from tiber.worker.queues import (
    DELIVERY_QUEUES,
    DLQ_EXCHANGE,
    DLQS,
    NOTIFICATIONS_EXCHANGE,
    TASK_QUEUES,
    channel_topology,
)


def test_every_channel_has_delivery_queue_and_dlq():
    """Each delivery channel maps to a (delivery, dead-letter) queue pair."""
    for channel in DeliveryChannel:
        delivery, dlq = channel_topology(channel)
        assert isinstance(delivery, Queue)
        assert isinstance(dlq, Queue)
        assert delivery.name == f"{channel.value}.delivery.queue"
        assert dlq.name == f"{channel.value}.dlq"


def test_delivery_queue_publishes_the_channel_routing_key():
    """The delivery queue binds its channel's ``notification.{ch}`` key."""
    for channel in DeliveryChannel:
        delivery, _ = channel_topology(channel)
        assert delivery.routing_key == f"notification.{channel.value}"
        assert delivery.exchange is NOTIFICATIONS_EXCHANGE
        assert delivery.durable


def test_delivery_queue_dead_letters_to_channel_dlq():
    """Exhausted/rejected jobs are dead-lettered to the channel DLQ."""
    for channel in DeliveryChannel:
        delivery, _ = channel_topology(channel)
        assert delivery.queue_arguments["x-dead-letter-exchange"] == DLQ_EXCHANGE.name
        assert (
            delivery.queue_arguments["x-dead-letter-routing-key"]
            == f"{channel.value}.dlq"
        )


def test_dlq_is_bound_and_durable():
    """The DLQ is durable and subscribes to the DLQ exchange on its key."""
    for channel in DeliveryChannel:
        _, dlq = channel_topology(channel)
        assert dlq.routing_key == f"{channel.value}.dlq"
        assert dlq.exchange is DLQ_EXCHANGE
        assert dlq.durable


def test_queue_sets_cover_all_channels():
    """CELERY queue sets include one delivery and one DLQ per channel."""
    assert len(DELIVERY_QUEUES) == len(list(DeliveryChannel))
    assert len(DLQS) == len(list(DeliveryChannel))
    assert len(TASK_QUEUES) == 2 * len(list(DeliveryChannel))
    assert set(TASK_QUEUES) == set(DELIVERY_QUEUES) | set(DLQS)

    names = {q.name for q in TASK_QUEUES}
    for channel in DeliveryChannel:
        assert f"{channel.value}.delivery.queue" in names
        assert f"{channel.value}.dlq" in names
