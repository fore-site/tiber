"""Ports used by the accept/process split."""

from typing import Literal, Protocol

from tiber.domain.entities import Notification
from tiber.domain.entities.notification_intake import NotificationIntake

OutboxPriority = Literal["high", "normal"]


class Outbox(Protocol):
    """Transactional outbox.

    Both methods write a row in the CURRENT transaction;
    a separate relay publishes rows to the broker after commit. That closes the
    "committed but never published" gap.

    The relay is not included here.
    """

    async def enqueue_intake(
        self, intake: NotificationIntake, *, priority: OutboxPriority
    ) -> None:
        """Queue an intake for the processor in the current transaction."""
        ...

    async def enqueue_dispatch(self, notification: Notification) -> None:
        """Queue a fan-out notification for the dispatcher in the current transaction."""
        ...
