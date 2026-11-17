from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import SenderIdentity
from ...domain.enums import DeliveryChannel
from ...domain.exceptions import SenderIdentityConflictError
from ...domain.repositories import SenderIdentityRepository
from ..models.sender_identity import SenderIdentityModel
from .sqlalchemy_errors import get_constraint_name

_SENDER_CONSTRAINTS = frozenset(
    {
        "sender_identities_project_channel_unique",
        "sender_identities_provider_domain_unique",
        "sender_identities_provider_domain_id_unique",
    }
)


class SQLAlchemySenderIdentityRepository(SenderIdentityRepository):
    """SQLAlchemy implementation of sender identity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to one request-scoped session."""
        self._session = session

    async def save(self, identity: SenderIdentity) -> SenderIdentity:
        """Persist sender identity state without committing."""
        try:
            async with self._session.begin_nested():
                model = await self._session.get(SenderIdentityModel, identity.id)
                if model is None:
                    model = SenderIdentityModel(id=identity.id)
                    self._session.add(model)
                model.project_id = identity.project_id
                model.channel = identity.channel
                model.provider = identity.provider
                model.from_email = identity.from_email
                model.display_name = identity.display_name
                model.reply_to = identity.reply_to
                model.domain = identity.domain
                model.provider_domain_id = identity.provider_domain_id
                model.status = identity.status
                model.dns_records = list(identity.dns_records)
                model.verified_at = identity.verified_at
                model.created_at = identity.created_at
                model.updated_at = identity.updated_at
                await self._session.flush()
        except IntegrityError as exc:
            if get_constraint_name(exc) in _SENDER_CONSTRAINTS:
                raise SenderIdentityConflictError(
                    "This sender or domain is already registered."
                ) from exc
            raise
        return identity

    async def get_by_id(self, id: UUID, project_id: UUID) -> SenderIdentity | None:
        """Get a sender identity by ID within its project."""
        model = await self._session.get(SenderIdentityModel, id)
        if model is None or model.project_id != project_id:
            return None
        return self._to_entity(model)

    async def get_for_project(
        self, project_id: UUID, channel: DeliveryChannel
    ) -> SenderIdentity | None:
        """Get the project's identity for one delivery channel."""
        model = await self._session.scalar(
            select(SenderIdentityModel).where(
                SenderIdentityModel.project_id == project_id,
                SenderIdentityModel.channel == channel,
            )
        )
        return self._to_entity(model) if model is not None else None

    async def get_by_domain(self, domain: str, provider: str) -> SenderIdentity | None:
        """Get the identity that already owns a provider domain."""
        model = await self._session.scalar(
            select(SenderIdentityModel).where(
                SenderIdentityModel.domain == domain.lower(),
                SenderIdentityModel.provider == provider,
            )
        )
        return self._to_entity(model) if model is not None else None

    async def list_by_project(self, project_id: UUID) -> list[SenderIdentity]:
        """List a project's sender identities, oldest first."""
        models = (
            await self._session.scalars(
                select(SenderIdentityModel)
                .where(SenderIdentityModel.project_id == project_id)
                .order_by(
                    SenderIdentityModel.created_at,
                    SenderIdentityModel.id,
                )
            )
        ).all()
        return [self._to_entity(model) for model in models]

    async def delete(self, id: UUID, project_id: UUID) -> bool:
        """Delete a project-scoped sender identity."""
        result = await self._session.execute(
            delete(SenderIdentityModel).where(
                SenderIdentityModel.id == id,
                SenderIdentityModel.project_id == project_id,
            )
        )
        await self._session.flush()
        return bool(cast(CursorResult, result).rowcount)

    @staticmethod
    def _to_entity(model: SenderIdentityModel) -> SenderIdentity:
        return SenderIdentity.reconstitute(
            id=model.id,
            project_id=model.project_id,
            channel=DeliveryChannel(model.channel),
            provider=model.provider,
            from_email=model.from_email,
            display_name=model.display_name,
            reply_to=model.reply_to,
            domain=model.domain,
            provider_domain_id=model.provider_domain_id,
            status=model.status,
            dns_records=tuple(model.dns_records or ()),
            verified_at=model.verified_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
