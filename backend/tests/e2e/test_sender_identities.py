"""End-to-end journeys for project-owned sender identities."""

from __future__ import annotations

from typing import Any

import pytest

from tiber.api.common import dependencies as deps
from tiber.application.ports.sender_domain import ProviderDomain

pytestmark = pytest.mark.e2e

AUTH = {"Authorization": "Bearer e2e"}


class FakeSenderDomainProvider:
    """Provider stand-in that records domain lifecycle calls."""

    name = "resend"

    def __init__(self) -> None:
        """Initialize empty provider state for one test."""
        self.domain: str | None = None
        self.domain_id = "domain-test-1"
        self.status = "not_started"
        self.records: tuple[dict[str, Any], ...] = (
            {
                "record": "DKIM",
                "name": "resend._domainkey",
                "type": "TXT",
                "value": "test-key",
                "status": "not_started",
            },
        )
        self.verified: list[str] = []
        self.deleted: list[str] = []

    async def create(self, domain: str) -> ProviderDomain:
        """Register a domain and return pending DNS records."""
        self.domain = domain
        return self._current()

    async def verify(self, domain_id: str) -> None:
        """Mark verification as requested and complete it immediately."""
        self.verified.append(domain_id)
        self.status = "verified"
        self.records = tuple(
            {**record, "status": "verified"} for record in self.records
        )

    async def get(self, domain_id: str) -> ProviderDomain:
        """Return the current fake domain state."""
        return self._current()

    async def delete(self, domain_id: str) -> None:
        """Record provider-side domain deletion."""
        self.deleted.append(domain_id)

    def _current(self) -> ProviderDomain:
        assert self.domain is not None
        return ProviderDomain(
            id=self.domain_id,
            name=self.domain,
            status=self.status,
            records=self.records,
        )


def sender_body(**overrides) -> dict:
    """Build a valid sender registration payload."""
    body = {
        "from_email": "notifications@acme.com",
        "display_name": "Acme",
        "reply_to": "support@acme.com",
    }
    body.update(overrides)
    return body


async def test_sender_lifecycle_returns_dns_and_verification_state(
    client, app, project
):
    """Register, list, verify, and delete one project sender."""
    provider = FakeSenderDomainProvider()
    app.dependency_overrides[deps.get_sender_domain_provider] = lambda: provider

    registered = await client.post(
        f"/v1/projects/{project.id}/senders",
        headers=AUTH,
        json=sender_body(),
    )

    assert registered.status_code == 201, registered.text
    body = registered.json()
    assert body["from_email"] == "notifications@acme.com"
    assert body["domain"] == "acme.com"
    assert body["status"] == "not_started"
    assert body["is_verified"] is False
    assert body["dns_records"][0]["record"] == "DKIM"
    assert provider.domain == "acme.com"

    listed = await client.get(
        f"/v1/projects/{project.id}/senders",
        headers=AUTH,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [body["id"]]

    verified = await client.post(
        f"/v1/projects/{project.id}/senders/{body['id']}/verification",
        headers=AUTH,
    )
    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"
    assert verified.json()["is_verified"] is True
    assert verified.json()["verified_at"] is not None
    assert provider.verified == [provider.domain_id]

    deleted = await client.delete(
        f"/v1/projects/{project.id}/senders/{body['id']}",
        headers=AUTH,
    )
    assert deleted.status_code == 204
    assert provider.deleted == [provider.domain_id]

    empty = await client.get(
        f"/v1/projects/{project.id}/senders",
        headers=AUTH,
    )
    assert empty.status_code == 200
    assert empty.json()["data"] == []


async def test_duplicate_sender_registration_is_rejected(client, app, project):
    """A project can only own one email sender identity."""
    provider = FakeSenderDomainProvider()
    app.dependency_overrides[deps.get_sender_domain_provider] = lambda: provider

    first = await client.post(
        f"/v1/projects/{project.id}/senders",
        headers=AUTH,
        json=sender_body(),
    )
    assert first.status_code == 201, first.text

    duplicate = await client.post(
        f"/v1/projects/{project.id}/senders",
        headers=AUTH,
        json=sender_body(from_email="other@acme.com"),
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "sender_identity_conflict"


async def test_missing_sender_means_the_tiber_fallback_is_used(client, project):
    """With no registered sender, the project list is empty."""
    response = await client.get(
        f"/v1/projects/{project.id}/senders",
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["data"] == []
