from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...application.auth import AuthAccount
from ...application.ports.auth_account_repository import (
    AccountIdentityConflictError,
    AuthAccountRepository,
)
from ..models.account import AccountModel


class SQLAlchemyAuthAccountRepository(AuthAccountRepository):
    """Persist authentication state stored alongside an account."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to one request-scoped session."""
        self._session = session

    async def add(self, account: AuthAccount) -> AuthAccount:
        """Insert a new account and flush generated timestamps."""
        model = AccountModel(
            id=account.id,
            email=account.email,
            role=account.role,
            is_verified=account.is_verified,
            is_active=account.is_active,
            auth_version=account.auth_version,
            pending_email=account.pending_email,
            password_hash=account.password_hash,
            github_id=account.github_id,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise AccountIdentityConflictError from exc
        account.created_at = model.created_at
        account.updated_at = model.updated_at
        return account

    async def save(self, account: AuthAccount) -> AuthAccount:
        """Update account authentication state without ending the transaction."""
        model = await self._session.get(AccountModel, account.id)
        if model is None:
            raise LookupError(f"Account {account.id} does not exist.")
        model.email = account.email
        model.role = account.role
        model.is_verified = account.is_verified
        model.is_active = account.is_active
        model.auth_version = account.auth_version
        model.pending_email = account.pending_email
        model.password_hash = account.password_hash
        model.github_id = account.github_id
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise AccountIdentityConflictError from exc
        await self._session.refresh(model)
        account.created_at = model.created_at
        account.updated_at = model.updated_at
        return account

    async def get_by_id(self, account_id: UUID) -> AuthAccount | None:
        """Load authentication state by account ID."""
        model = await self._session.get(AccountModel, account_id)
        return self._to_record(model) if model is not None else None

    async def get_by_email(self, email: str) -> AuthAccount | None:
        """Load authentication state by case-insensitive email address."""
        model = await self._session.scalar(
            select(AccountModel).where(AccountModel.email == email)
        )
        return self._to_record(model) if model is not None else None

    async def get_by_email_or_pending_email(self, email: str) -> AuthAccount | None:
        """Load an account by its active or pending email address."""
        model = await self._session.scalar(
            select(AccountModel).where(
                or_(
                    AccountModel.email == email,
                    AccountModel.pending_email == email,
                )
            )
        )
        return self._to_record(model) if model is not None else None

    async def get_by_github_id(self, github_id: str) -> AuthAccount | None:
        """Load authentication state by the linked GitHub user ID."""
        model = await self._session.scalar(
            select(AccountModel).where(AccountModel.github_id == github_id)
        )
        return self._to_record(model) if model is not None else None

    @staticmethod
    def _to_record(model: AccountModel) -> AuthAccount:
        return AuthAccount(
            id=model.id,
            email=model.email,
            role=model.role,
            is_verified=model.is_verified,
            is_active=model.is_active,
            auth_version=model.auth_version,
            pending_email=model.pending_email,
            password_hash=model.password_hash,
            github_id=model.github_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
