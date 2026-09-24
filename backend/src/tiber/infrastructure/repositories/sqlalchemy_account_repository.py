from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import Account
from ...domain.repositories import AccountRepository
from ..models.account import AccountModel


class SQLAlchemyAccountRepository(AccountRepository):
    """SQLAlchemy implementation of the id-only AccountRepository.

    The domain's Account entity carries only an id: Tiber is a
    notification-delivery platform, not an authentication service, so this
    repository persists ownership roots and nothing else. The underlying
    ``accounts`` table doubles as the auth store (credentials, verification,
    role) — that data is written and read by the auth capability's own
    adapters against ``AccountModel`` directly, never mapped through here.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an async session."""
        self._session = session

    async def save(self, account: Account) -> Account:
        """Persist an account ownership root.

        The ``email`` column is NOT NULL (it is the auth store's identity),
        but the domain entity carries no email — so a derived placeholder
        keeps the row insertable without inventing domain state. The real
        email is set by the auth adapter when the account is claimed.
        """
        model = AccountModel(
            id=account.id,
            email=f"account-{account.id}@accounts.invalid",
        )
        self._session.add(model)
        await self._session.flush()
        return account

    async def get_by_id(self, id: UUID) -> Account | None:
        """Get an account ownership root by its ID."""
        model = await self._session.get(AccountModel, id)
        return Account(id=model.id) if model else None
