"""Celery task routing.

Delivery routing is channel-aware: the publisher stamps each job with a
``notification.{channel}`` routing key (``NotificationJobPayload.routing_key``)
that the broker uses to place the message on the matching channel's delivery
queue. The route below only pins the task to the notifications exchange; the
final queue is resolved from the per-job routing key at publish time.
"""

from .queues import NOTIFICATIONS_EXCHANGE

task_routes = {
    "notification.process": {
        "exchange": NOTIFICATIONS_EXCHANGE.name,
    },
}
