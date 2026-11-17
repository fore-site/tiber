from __future__ import annotations

from typing import Any

import httpx

from ....application.ports.sender_domain import ProviderDomain, SenderDomainProvider
from ....domain.exceptions import (
    InvalidEntityAttributeError,
    ProviderUnavailableError,
    SenderIdentityConflictError,
)

_BASE_URL = "https://api.resend.com"


class ResendDomainProvider(SenderDomainProvider):
    """Manage sending domains through the Resend Domains API."""

    def __init__(self, *, api_key: str) -> None:
        """Configure the provider with a Resend API key."""
        if not api_key:
            raise ValueError("Resend API key must not be empty")
        self._api_key = api_key

    @property
    def name(self) -> str:
        """Return the stable provider identifier."""
        return "resend"

    async def create(self, domain: str) -> ProviderDomain:
        """Register a domain and return its DNS verification records."""
        response = await self._request(
            "POST",
            "/domains",
            json={"name": domain},
        )
        if response.status_code == 409:
            raise SenderIdentityConflictError(
                "This sender domain is already registered."
            )
        if response.status_code == 422:
            raise InvalidEntityAttributeError(self._error_message(response))
        if response.is_error:
            raise ProviderUnavailableError("Resend")
        return self._to_domain(response)

    async def verify(self, domain_id: str) -> None:
        """Ask Resend to start verifying a domain's DNS records."""
        response = await self._request("POST", f"/domains/{domain_id}/verify", json={})
        if response.status_code == 404:
            raise ProviderUnavailableError("Resend")
        if response.is_error:
            raise ProviderUnavailableError("Resend")

    async def get(self, domain_id: str) -> ProviderDomain:
        """Retrieve one domain's current verification state."""
        response = await self._request("GET", f"/domains/{domain_id}")
        if response.status_code == 404:
            raise ProviderUnavailableError("Resend")
        if response.is_error:
            raise ProviderUnavailableError("Resend")
        return self._to_domain(response)

    async def delete(self, domain_id: str) -> None:
        """Remove a domain; an already-missing domain is treated as removed."""
        response = await self._request("DELETE", f"/domains/{domain_id}")
        if response.status_code == 404:
            return
        if response.is_error:
            raise ProviderUnavailableError("Resend")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.request(
                    method,
                    f"{_BASE_URL}{path}",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=json,
                )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("Resend") from exc
        if response.status_code in (408, 429) or response.status_code >= 500:
            raise ProviderUnavailableError("Resend")
        return response

    @staticmethod
    def _to_domain(response: httpx.Response) -> ProviderDomain:
        try:
            payload = response.json()
            records = payload.get("records") or []
            return ProviderDomain(
                id=payload["id"],
                name=payload["name"],
                status=payload["status"],
                records=tuple(record for record in records if isinstance(record, dict)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailableError("Resend") from exc

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            message = response.json().get("message")
        except AttributeError, TypeError, ValueError:
            message = None
        if isinstance(message, str) and message.strip():
            return message.strip()
        return "Resend rejected the sender domain."
