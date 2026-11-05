from uuid import UUID

from ...application.ports.message_publisher import MessagePublisher
from ...domain.entities import Notification
from ...events.job_payload import NotificationJobPayload
from ...worker.celery_app import celery_app
from ...worker.queues import INTERNAL_QUEUE


class CeleryPublisher(MessagePublisher):
    """Publish intake and delivery jobs to Celery/RabbitMQ.

    Intake work is sent to the internal worker queue. Notification work is
    routed to the channel-specific delivery queue.
    """

    async def publish_intake(self, intake_id: UUID) -> None:
        """Publish an intake identifier for asynchronous fan-out."""
        celery_app.send_task(
            "notification.intake",
            args=[str(intake_id)],
            queue=INTERNAL_QUEUE.name,
            routing_key=INTERNAL_QUEUE.routing_key,
        )

    async def publish_notification(self, notification: Notification) -> None:
        """Publish a stable, self-contained notification job."""
        job = NotificationJobPayload.from_entity(notification)
        celery_app.send_task(
            "notification.process",
            args=[job.to_json_dict()],
            routing_key=job.routing_key,
        )
