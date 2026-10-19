"""Unit of work port.

A unit of work marks one atomic piece of work against the database: everything
done inside ``async with uow:`` is committed together when the block exits
normally, and rolled back together when it raises.

    async with self._uow:
        await self._intakes.add(intake)
        await self._outbox.enqueue_intake(intake, priority="normal")
    # <- committed here, and only here

Contract the services rely on
-----------------------------
* Clean exit commits; any exception (including cancellation) rolls back and is
  re-raised. A unit of work never swallows exceptions.
* Re-enterable: after a block ends, the same instance can be entered again and
  starts a fresh transaction (``IntakeProcessor`` opens several in a row).
* Nesting is allowed. An inner block is a savepoint: if it raises, only the inner
  work is undone, and the exception still propagates to the outer block.
* Repositories never commit or roll back. Only the unit of work does.
* One instance per request or task. Instances are not safe to share between
  concurrent tasks.
"""

from types import TracebackType
from typing import Protocol, Self


class UnitOfWorkError(RuntimeError):
    """The unit of work was used in a way that would break atomicity."""


class UnitOfWork(Protocol):
    """Atomic transaction boundary used by every write service."""

    async def __aenter__(self) -> Self:
        """Open the outermost transaction or a nested savepoint."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Commit on success; roll back and re-raise on any exception."""
        ...
