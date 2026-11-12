from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ...domain.entities import WebhookEndpoint
from ...domain.enums import WebhookEventType
from ...domain.repositories import WebhookEndpointRepository
from ...infrastructure.models.webhook_endpoint import WebhookEndpointModel


class SQLAlchemyWebhookEndpointRepository(WebhookEndpointRepository):
    """SQLAlchemy implementation of the WebhookEndpointRepository."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an async session."""
        self._session = session

    async def save(self, endpoint: WebhookEndpoint) -> WebhookEndpoint:
        """Insert or update a webhook endpoint."""
        await self._session.merge(self._to_model(endpoint))
        await self._session.flush()
        return endpoint

    async def get_by_id(self, id: UUID, project_id: UUID) -> WebhookEndpoint | None:
        """Get a webhook endpoint by its ID within a project's scope."""
        model = await self._session.get(WebhookEndpointModel, id)
        if model is not None and model.project_id != project_id:
            return None
        return self._to_entity(model) if model is not None else None

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
    ) -> list[WebhookEndpoint]:
        """List a page of a project's endpoints, newest first."""
        statement = select(WebhookEndpointModel).where(
            WebhookEndpointModel.project_id == project_id
        )
        if cursor is not None:
            statement = statement.where(self._before(cursor))
        models = (
            await self._session.scalars(
                statement.order_by(
                    WebhookEndpointModel.created_at.desc(),
                    WebhookEndpointModel.id.desc(),
                ).limit(limit)
            )
        ).all()
        return [self._to_entity(model) for model in models]

    async def list_by_event(
        self,
        project_id: UUID,
        event_type: WebhookEventType,
        limit: int,
        *,
        cursor: tuple[datetime, UUID] | None = None,
    ) -> list[WebhookEndpoint]:
        """List a page of the project's endpoints subscribed to one event type."""
        statement = (
            select(WebhookEndpointModel)
            .where(WebhookEndpointModel.project_id == project_id)
            .where(WebhookEndpointModel.events.contains([event_type.value]))
        )
        if cursor is not None:
            statement = statement.where(self._before(cursor))
        models = (
            await self._session.scalars(
                statement.order_by(
                    WebhookEndpointModel.created_at.desc(),
                    WebhookEndpointModel.id.desc(),
                ).limit(limit)
            )
        ).all()
        return [self._to_entity(model) for model in models]

    async def delete(self, id: UUID, project_id: UUID) -> bool:
        """Delete an endpoint; False when it does not exist in the project."""
        result = await self._session.execute(
            delete(WebhookEndpointModel).where(
                WebhookEndpointModel.id == id,
                WebhookEndpointModel.project_id == project_id,
            )
        )
        await self._session.flush()
        return bool(cast(CursorResult, result).rowcount)

    @staticmethod
    def _before(cursor: tuple[datetime, UUID]) -> ColumnElement[bool]:
        """Return the keyset predicate strictly before one ``(time, id)``."""
        created_at, endpoint_id = cursor
        return or_(
            WebhookEndpointModel.created_at < created_at,
            and_(
                WebhookEndpointModel.created_at == created_at,
                WebhookEndpointModel.id < endpoint_id,
            ),
        )

    @staticmethod
    def _to_model(entity: WebhookEndpoint) -> WebhookEndpointModel:
        return WebhookEndpointModel(
            id=entity.id,
            project_id=entity.project_id,
            url=entity.url,
            events=[event.value for event in entity.events],
            encrypted_signing_secret=entity.encrypted_signing_secret,
            secret_prefix=entity.secret_prefix,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _to_entity(model: WebhookEndpointModel) -> WebhookEndpoint:
        return WebhookEndpoint.reconstitute(
            id=model.id,
            project_id=model.project_id,
            url=model.url,
            events=[WebhookEventType(event) for event in model.events],
            encrypted_signing_secret=model.encrypted_signing_secret,
            secret_prefix=model.secret_prefix,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
