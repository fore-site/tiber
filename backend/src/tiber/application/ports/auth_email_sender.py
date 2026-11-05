"""Port for transactional authentication email delivery."""

from __future__ import annotations

from typing import Protocol


class AuthEmailDeliveryError(RuntimeError):
    """Raised when an authentication email cannot be delivered."""


class AuthEmailSender(Protocol):
    """Deliver verification and password-reset messages."""

    async def send(self, recipient: str, subject: str, body: str) -> None:
        """Deliver a plain-text authentication message."""
        ...
