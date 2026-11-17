from __future__ import annotations

from uuid import UUID

from tiber.application.ports.sender_domain import SenderDomainProvider
from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.core.logging import get_logger
from tiber.domain.entities import SenderIdentity
from tiber.domain.entities.sender_identity import (
    normalize_sender_email,
    sender_domain,
)
from tiber.domain.enums import DeliveryChannel
from tiber.domain.exceptions import (
    EntityNotFoundError,
    ProviderUnavailableError,
    SenderIdentityConflictError,
)
from tiber.domain.repositories import SenderIdentityRepository

logger = get_logger(__name__)


class SenderIdentityService:
    """Register, verify, and remove project-owned email sender identities."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        sender_repository: SenderIdentityRepository,
        domain_provider: SenderDomainProvider | None,
    ) -> None:
        """Bind the service to its transaction, repository, and domain provider."""
        self._uow = unit_of_work
        self._senders = sender_repository
        self._domains = domain_provider

    async def register(
        self,
        *,
        project_id: UUID,
        from_email: str,
        display_name: str | None,
        reply_to: str | None,
    ) -> SenderIdentity:
        """Register a sender domain and persist its pending identity."""
        provider = self._require_domain_provider()
        normalized_email = normalize_sender_email(str(from_email))
        domain = sender_domain(normalized_email)

        async with self._uow:
            existing = await self._senders.get_for_project(
                project_id, DeliveryChannel.EMAIL
            )
            if existing is not None:
                raise SenderIdentityConflictError(
                    "This project already has an email sender identity."
                )
            if await self._senders.get_by_domain(domain, provider.name):
                raise SenderIdentityConflictError(
                    "This sender domain is already registered."
                )

        provider_domain = await provider.create(domain)
        identity = SenderIdentity.create(
            project_id=project_id,
            provider=provider.name,
            provider_domain_id=provider_domain.id,
            from_email=normalized_email,
            display_name=display_name,
            reply_to=reply_to,
            status=provider_domain.status,
            dns_records=provider_domain.records,
        )
        try:
            async with self._uow:
                return await self._senders.save(identity)
        except Exception:
            await self._delete_provider_domain(provider_domain.id)
            raise

    async def list(self, project_id: UUID) -> list[SenderIdentity]:
        """List a project's sender identities."""
        async with self._uow:
            return await self._senders.list_by_project(project_id)

    async def get(self, project_id: UUID, sender_id: UUID) -> SenderIdentity:
        """Get one project-scoped sender identity."""
        async with self._uow:
            identity = await self._senders.get_by_id(sender_id, project_id)
            if identity is None:
                raise EntityNotFoundError(SenderIdentity, str(sender_id))
            return identity

    async def verify(self, project_id: UUID, sender_id: UUID) -> SenderIdentity:
        """Trigger provider verification and persist the refreshed state."""
        provider = self._require_domain_provider()
        identity = await self.get(project_id, sender_id)
        await provider.verify(identity.provider_domain_id)
        provider_domain = await provider.get(identity.provider_domain_id)
        updated = identity.with_provider_state(
            status=provider_domain.status,
            dns_records=provider_domain.records,
        )
        async with self._uow:
            return await self._senders.save(updated)

    async def delete(self, project_id: UUID, sender_id: UUID) -> None:
        """Remove the provider domain, then the project sender identity."""
        provider = self._require_domain_provider()
        identity = await self.get(project_id, sender_id)
        await provider.delete(identity.provider_domain_id)
        async with self._uow:
            deleted = await self._senders.delete(identity.id, project_id)
        if not deleted:
            raise EntityNotFoundError(SenderIdentity, str(sender_id))

    async def resolve_for_delivery(
        self, project_id: UUID, channel: DeliveryChannel
    ) -> str | None:
        """Return a verified From value, or None to use the Tiber fallback."""
        if channel is not DeliveryChannel.EMAIL:
            return None
        async with self._uow:
            identity = await self._senders.get_for_project(project_id, channel)
        if identity is None or not identity.is_verified:
            return None
        return identity.formatted_from

    def _require_domain_provider(self) -> SenderDomainProvider:
        if self._domains is None:
            raise ProviderUnavailableError("Resend")
        return self._domains

    async def _delete_provider_domain(self, provider_domain_id: str) -> None:
        if self._domains is None:
            return
        try:
            await self._domains.delete(provider_domain_id)
        except Exception:
            logger.warning(
                "Could not clean up sender domain after persistence failure",
                provider_domain_id=provider_domain_id,
            )
