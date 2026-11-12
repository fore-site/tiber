"""Client-registered webhook endpoints (registration side).

The API Service owns registration; the Worker Service owns dispatch. Sharing
the endpoint table is the contract between them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from tiber.application.pagination import (
    CursorPage,
    decode_time_id_cursor,
    encode_cursor,
)
from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.core.encryption import encrypt_secret
from tiber.core.security import generate_webhook_secret
from tiber.domain.entities import WebhookEndpoint
from tiber.domain.enums import WebhookEventType
from tiber.domain.exceptions import EntityNotFoundError, InvalidEntityAttributeError
from tiber.domain.repositories import WebhookEndpointRepository


@dataclass(frozen=True)
class IssuedWebhookEndpoint:
    """A newly registered endpoint together with its plaintext secret.

    The plaintext is returned exactly once, at registration. Only its encrypted
    form is persisted, so it can never be shown again.
    """

    endpoint: WebhookEndpoint
    signing_secret: str


class WebhookEndpointService:
    """Project-scoped lifecycle for client callbacks."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        endpoint_repository: WebhookEndpointRepository,
    ) -> None:
        """Initialize the service with its transaction boundary and repository."""
        self._unit_of_work = unit_of_work
        self._endpoints = endpoint_repository

    async def create(
        self,
        *,
        project_id: UUID,
        url: str,
        events: list[WebhookEventType],
    ) -> IssuedWebhookEndpoint:
        """Register an endpoint and issue its signing secret."""
        if not events:
            raise InvalidEntityAttributeError(
                "A webhook endpoint must subscribe to at least one event."
            )
        secret, prefix = generate_webhook_secret()
        endpoint = WebhookEndpoint.create(
            project_id=project_id,
            url=url,
            events=list(dict.fromkeys(events)),
            encrypted_signing_secret=encrypt_secret(secret),
            secret_prefix=prefix,
        )
        async with self._unit_of_work:
            await self._endpoints.save(endpoint)
        return IssuedWebhookEndpoint(endpoint=endpoint, signing_secret=secret)

    async def list(
        self, project_id: UUID, *, limit: int = 50, cursor: str | None = None
    ) -> CursorPage[WebhookEndpoint]:
        """List a page of a project's registered endpoints, newest first."""
        after = decode_time_id_cursor(cursor, time_field="created_at")
        endpoints = await self._endpoints.list_by_project(
            project_id, limit + 1, cursor=after
        )
        items = endpoints[:limit]
        next_cursor = (
            encode_cursor(
                created_at=items[-1].created_at.isoformat(),
                id=items[-1].id,
            )
            if len(endpoints) > limit
            else None
        )
        return CursorPage(items=items, next_cursor=next_cursor)

    async def get(self, project_id: UUID, webhook_id: UUID) -> WebhookEndpoint:
        """Return one endpoint, scoped to the project."""
        endpoint = await self._endpoints.get_by_id(webhook_id, project_id)
        if endpoint is None:
            raise EntityNotFoundError(WebhookEndpoint, str(webhook_id))
        return endpoint

    async def update(
        self,
        *,
        project_id: UUID,
        webhook_id: UUID,
        url: str | None = None,
        events: list[WebhookEventType] | None = None,
    ) -> WebhookEndpoint:
        """Replace the endpoint's URL and/or subscriptions.

        The signing secret is deliberately not rotatable here: rotation would
        invalidate every in-flight callback's signature, so it deserves its own
        endpoint and a client-controlled cutover.
        """
        endpoint = await self.get(project_id, webhook_id)
        if events is not None and not events:
            raise InvalidEntityAttributeError(
                "A webhook endpoint must subscribe to at least one event."
            )
        updated = replace(
            endpoint,
            url=url if url is not None else endpoint.url,
            events=(
                list(dict.fromkeys(events)) if events is not None else endpoint.events
            ),
            updated_at=datetime.now(UTC),
        )
        async with self._unit_of_work:
            await self._endpoints.save(updated)
        return updated

    async def delete(self, project_id: UUID, webhook_id: UUID) -> None:
        """Delete an endpoint; a missing endpoint is a not-found error."""
        async with self._unit_of_work:
            deleted = await self._endpoints.delete(webhook_id, project_id)
        if not deleted:
            raise EntityNotFoundError(WebhookEndpoint, str(webhook_id))
