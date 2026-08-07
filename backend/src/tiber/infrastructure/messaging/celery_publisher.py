from ...application.ports.message_publisher import MessagePublisher
from ...domain.entities import Notification
from ...events.job_payload import NotificationJobPayload
from ...worker.tasks.notification import process_notification  # Celery task


class CeleryPublisher(MessagePublisher):
    """Publish a stable, self-contained notification job to Celery/RabbitMQ.

    The payload is built from the domain entity and routed to the channel's
    delivery queue via its ``notification.{channel}`` routing key.
    """

    async def publish_notification(self, notification: Notification) -> None:
        """Publish a notification job with its stable worker payload."""
        job = NotificationJobPayload.from_entity(notification)
        process_notification.apply_async(
            args=[job.to_json_dict()],
            routing_key=job.routing_key,
        )
