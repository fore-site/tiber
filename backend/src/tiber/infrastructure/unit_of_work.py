"""SQLAlchemy implementation of the unit of work port.

How it fits together
--------------------
The unit of work and every repository share ONE ``AsyncSession``, created per
HTTP request or per queue message. The repositories issue statements on that
session; the unit of work decides when the transaction ends. Wiring, in your
composition root / DI container:

    async with session_factory() as session:          # closes the session at the end
        uow = SqlAlchemyUnitOfWork(session)
        recipients = SqlRecipientRepository(session)
        intakes = SqlNotificationIntakeRepository(session)
        outbox = SqlOutbox(session)
        service = NotificationIntakeService(
            unit_of_work=uow,
            recipient_resolution=RecipientResolutionService(recipient_repository=recipients),
            intake_repository=intakes,
            outbox=outbox,
            ...,
        )
        await service.accept(command)

Create the session factory with ``expire_on_commit=False`` so objects stay usable
after a commit (lazy loading after commit raises in async SQLAlchemy).

Rules for repositories written against this
-------------------------------------------
* Never call ``session.commit()`` or ``session.rollback()``.
* ``save`` / ``add`` call ``session.flush()`` so constraint violations surface at
  the call site (the merge ordering and idempotency handling depend on this).
* Where a service retries after a unique violation (``RecipientAddressTakenError``,
  ``IntakeAlreadyExistsError``), wrap the flush in ``session.begin_nested()`` so a
  failed INSERT rolls back only the savepoint and the transaction stays usable.

What it does not do
-------------------
* Close the session (the scope that created it does).
* Set an isolation level; the engine default applies (READ COMMITTED on Postgres).
* Detect writes that were already flushed outside a ``with`` block. Keep all
  writes inside it.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from tiber.application.ports.unit_of_work import UnitOfWorkError


class SqlAlchemyUnitOfWork:
    """SQLAlchemy Unit of Work adapter."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the sessionn."""
        self._session = session
        self._depth = 0
        self._savepoints: list[AsyncSessionTransaction] = []

    @property
    def session(self) -> AsyncSession:
        """For composition and tests only; services must not reach for it."""
        return self._session

    @property
    def depth(self) -> int:
        """0 when idle, 1 inside the outermost block, 2+ inside nested blocks."""
        return self._depth

    async def __aenter__(self) -> Self:
        """Start the outermost transaction, or a savepoint when nested."""
        if self._depth == 0:
            await self._prepare_outermost()
        else:
            # Nested block: a savepoint, so an inner failure can be undone alone.
            self._savepoints.append(await self._session.begin_nested())
        self._depth += 1
        return self

    async def _prepare_outermost(self) -> None:
        """Make sure the new transaction starts clean.

        SQLAlchemy begins a transaction automatically on the first statement, so
        a read made OUTSIDE a block (``IntakeProcessor`` does this) leaves a
        transaction open. Reuse would hand the block a stale snapshot, and
        silently committing it could persist work done outside the block.
        """
        session = self._session
        if not session.in_transaction():
            return
        if session.new or session.dirty or session.deleted:
            raise UnitOfWorkError(
                "The session has pending changes made outside a unit of work. "
                "Perform all writes inside `async with uow:`."
            )
        # Only reads so far: end that transaction and start a fresh one.
        await session.rollback()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Commit the outermost block, or release/roll back the savepoint."""
        if self._depth == 0:
            raise UnitOfWorkError("Unit of work exited more times than it was entered.")
        self._depth -= 1

        if self._depth > 0:
            await self._exit_nested(failed=exc_type is not None)
            return None  # never suppress the exception

        if exc_type is None:
            await self._commit()
        else:
            await self._rollback()
        return None  # never suppress the exception

    async def _exit_nested(self, *, failed: bool) -> None:
        savepoint = self._savepoints.pop()
        if failed:
            await savepoint.rollback()  # undo only the inner work
        else:
            await savepoint.commit()  # release the savepoint; outer commit decides

    async def _commit(self) -> None:
        try:
            await self._session.commit()
        except BaseException:
            # Commit itself can fail (deferred constraints, connection loss).
            await self._rollback()
            raise

    async def _rollback(self) -> None:
        # Shielded so a cancelled request still returns its connection cleanly.
        await asyncio.shield(self._session.rollback())
        self._savepoints.clear()
