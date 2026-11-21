"""Recipient purge: the cutoff the service applies, and nothing wider."""

from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType

import pytest

from tiber.application.services.recipient_management import (
    RECIPIENT_PURGE_GRACE_PERIOD,
    RecipientManagementService,
)


class _RecordingRepository:
    """Record the purge request instead of reaching a database."""

    def __init__(self, removed: int = 3) -> None:
        self.calls: list[tuple[datetime, int]] = []
        self.removed = removed

    async def purge_expired(self, deleted_before: datetime, limit: int) -> int:
        """Store the arguments and report a fixed number of removed rows."""
        self.calls.append((deleted_before, limit))
        return self.removed


class _NullUnitOfWork:
    """Stand in for the transaction boundary; the repository does the work."""

    async def __aenter__(self) -> _NullUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


@pytest.mark.asyncio
async def test_purge_uses_the_grace_period_behind_now_and_the_requested_limit():
    """The service, not the caller, decides which tombstones are old enough."""
    repository = _RecordingRepository()
    service = RecipientManagementService(
        unit_of_work=_NullUnitOfWork(),
        recipient_repository=repository,
    )

    before = datetime.now(UTC)
    removed = await service.purge_expired(limit=25)
    after = datetime.now(UTC)

    assert removed == 3
    assert len(repository.calls) == 1
    cutoff, limit = repository.calls[0]
    assert limit == 25
    assert (
        before - RECIPIENT_PURGE_GRACE_PERIOD
        <= cutoff
        <= after - RECIPIENT_PURGE_GRACE_PERIOD
    )
