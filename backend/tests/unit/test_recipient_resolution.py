"""Recipient resolution for registered recipients.

Deletion is soft: the row survives for delivery history, so the resolver - not
just the repository - must treat a deleted recipient as missing.
"""

from uuid import UUID, uuid4

import pytest

from tiber.application.services.recipient_resolution import RecipientResolutionService
from tiber.domain.entities import Recipient
from tiber.domain.exceptions import EntityNotFoundError


class _FakeRecipients:
    """Minimal stand-in for the repository lookup the resolver performs."""

    def __init__(self, recipient: Recipient | None) -> None:
        """Store the row the lookup returns."""
        self.recipient = recipient

    async def get_by_external_id(
        self, external_id: str, project_id: UUID
    ) -> Recipient | None:
        """Return the configured row, or None for an unknown identifier."""
        return self.recipient


def _recipient() -> Recipient:
    """Build a registered recipient with no addresses."""
    return Recipient.create(project_id=uuid4(), external_id="user-1", addresses={})


@pytest.mark.asyncio
async def test_registered_recipient_resolves_by_external_id() -> None:
    """A registered recipient resolves by the client's identifier."""
    recipient = _recipient()
    service = RecipientResolutionService(
        recipient_repository=_FakeRecipients(recipient)
    )

    resolved = await service.resolve(
        project_id=recipient.project_id,
        recipient_external_id="user-1",
        addresses={},
    )

    assert resolved is recipient


@pytest.mark.asyncio
async def test_deleted_recipient_does_not_resolve() -> None:
    """Deletion hides the recipient even if a lookup still returns the row."""
    deleted = _recipient().delete()
    service = RecipientResolutionService(recipient_repository=_FakeRecipients(deleted))

    with pytest.raises(EntityNotFoundError):
        await service.resolve(
            project_id=deleted.project_id,
            recipient_external_id="user-1",
            addresses={},
        )


@pytest.mark.asyncio
async def test_unknown_recipient_does_not_resolve() -> None:
    """An identifier the project never registered does not resolve."""
    service = RecipientResolutionService(recipient_repository=_FakeRecipients(None))

    with pytest.raises(EntityNotFoundError):
        await service.resolve(
            project_id=uuid4(),
            recipient_external_id="user-1",
            addresses={},
        )
