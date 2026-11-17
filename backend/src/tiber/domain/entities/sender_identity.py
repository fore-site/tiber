from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from email.utils import formataddr
from typing import Any
from uuid import UUID, uuid4

from ..enums import DeliveryChannel
from ..exceptions import InvalidEntityAttributeError

VERIFIED_SENDER_STATUSES = frozenset({"verified", "partially_verified"})


def normalize_sender_email(value: str) -> str:
    """Validate a sender email address and normalize its domain."""
    if not value or value != value.strip():
        raise InvalidEntityAttributeError(
            "Sender email must not be empty or padded with whitespace"
        )
    local, separator, domain = value.rpartition("@")
    if (
        not separator
        or not local
        or not domain
        or any(character.isspace() for character in value)
        or "\r" in value
        or "\n" in value
    ):
        raise InvalidEntityAttributeError("Sender email must be a valid email address")
    if len(value) > 320 or len(domain) > 253:
        raise InvalidEntityAttributeError("Sender email is too long")
    return f"{local}@{domain.lower()}"


def sender_domain(value: str) -> str:
    """Return the normalized domain of a validated sender email."""
    return normalize_sender_email(value).rpartition("@")[2]


@dataclass(frozen=True, kw_only=True)
class SenderIdentity:
    """A project-owned address used as the email From identity."""

    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    channel: DeliveryChannel
    provider: str
    from_email: str
    display_name: str | None
    reply_to: str | None
    domain: str
    provider_domain_id: str
    status: str
    dns_records: tuple[dict[str, Any], ...]
    verified_at: datetime | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate persisted sender identity state."""
        normalize_sender_email(self.from_email)
        if self.reply_to is not None:
            normalize_sender_email(self.reply_to)
        if self.domain != sender_domain(self.from_email):
            raise InvalidEntityAttributeError(
                "Sender domain must match the sender email"
            )
        if not self.provider or not self.provider_domain_id or not self.status:
            raise InvalidEntityAttributeError(
                "Sender provider, domain id, and status must not be empty"
            )
        if self.display_name is not None:
            if not self.display_name.strip():
                raise InvalidEntityAttributeError(
                    "Sender display name must not be empty"
                )
            if len(self.display_name) > 100:
                raise InvalidEntityAttributeError(
                    "Sender display name must be 100 characters or fewer"
                )
            if "\r" in self.display_name or "\n" in self.display_name:
                raise InvalidEntityAttributeError(
                    "Sender display name must not contain line breaks"
                )

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        provider: str,
        provider_domain_id: str,
        from_email: str,
        display_name: str | None,
        reply_to: str | None,
        status: str,
        dns_records: tuple[dict[str, Any], ...],
    ) -> SenderIdentity:
        """Create a sender identity from provider-issued domain state."""
        normalized_email = normalize_sender_email(from_email)
        now = datetime.now(UTC)
        verified = status in VERIFIED_SENDER_STATUSES
        return cls(
            project_id=project_id,
            channel=DeliveryChannel.EMAIL,
            provider=provider,
            from_email=normalized_email,
            display_name=display_name,
            reply_to=normalize_sender_email(reply_to) if reply_to else None,
            domain=sender_domain(normalized_email),
            provider_domain_id=provider_domain_id,
            status=status,
            dns_records=dns_records,
            verified_at=now if verified else None,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        channel: DeliveryChannel,
        provider: str,
        from_email: str,
        display_name: str | None,
        reply_to: str | None,
        domain: str,
        provider_domain_id: str,
        status: str,
        dns_records: tuple[dict[str, Any], ...],
        verified_at: datetime | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> SenderIdentity:
        """Rebuild a sender identity from persisted state."""
        return cls(
            id=id,
            project_id=project_id,
            channel=channel,
            provider=provider,
            from_email=from_email,
            display_name=display_name,
            reply_to=reply_to,
            domain=domain,
            provider_domain_id=provider_domain_id,
            status=status,
            dns_records=dns_records,
            verified_at=verified_at,
            created_at=created_at,
            updated_at=updated_at,
        )

    @property
    def is_verified(self) -> bool:
        """Whether Resend currently permits sending from this domain."""
        return self.status in VERIFIED_SENDER_STATUSES

    @property
    def formatted_from(self) -> str:
        """Return the RFC 5322 From value used by the email provider."""
        if not self.display_name:
            return self.from_email
        return formataddr((self.display_name, self.from_email))

    def with_provider_state(
        self,
        *,
        status: str,
        dns_records: tuple[dict[str, Any], ...],
    ) -> SenderIdentity:
        """Apply refreshed verification state returned by the provider."""
        if not status:
            raise InvalidEntityAttributeError("Sender status must not be empty")
        now = datetime.now(UTC)
        verified = status in VERIFIED_SENDER_STATUSES
        return replace(
            self,
            status=status,
            dns_records=dns_records,
            verified_at=(
                self.verified_at
                if verified and self.verified_at is not None
                else (now if verified else None)
            ),
            updated_at=now,
        )
