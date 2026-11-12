"""Project-scoped webhook endpoint registration.

Dispatch lives in the Worker Service; this router only manages what is
registered.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from ...application.services.webhook_endpoint import WebhookEndpointService
from ...infrastructure.models import ProjectModel
from ..dependencies import (
    enforce_authenticated_rate_limit,
    get_authenticated_project,
    get_webhook_endpoint_service,
)
from ..schemas.webhook import (
    WebhookEndpointCreateRequest,
    WebhookEndpointIssuedResponse,
    WebhookEndpointPageResponse,
    WebhookEndpointResponse,
    WebhookEndpointUpdateRequest,
)

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


@router.post(
    "/projects/{project_id}/webhooks",
    response_model=WebhookEndpointIssuedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_webhook(
    payload: WebhookEndpointCreateRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[WebhookEndpointService, Depends(get_webhook_endpoint_service)],
) -> WebhookEndpointIssuedResponse:
    """Register a callback URL and return its signing secret once."""
    issued = await service.create(
        project_id=project.id,
        url=str(payload.url),
        events=payload.events,
    )
    return WebhookEndpointIssuedResponse.from_issued(
        issued.endpoint, issued.signing_secret
    )


@router.get(
    "/projects/{project_id}/webhooks",
    response_model=WebhookEndpointPageResponse,
)
async def list_webhooks(
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[WebhookEndpointService, Depends(get_webhook_endpoint_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> WebhookEndpointPageResponse:
    """List a page of the project's registered webhook endpoints."""
    page = await service.list(project.id, limit=limit, cursor=cursor)
    return WebhookEndpointPageResponse(
        data=[WebhookEndpointResponse.from_entity(endpoint) for endpoint in page.items],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/projects/{project_id}/webhooks/{webhook_id}",
    response_model=WebhookEndpointResponse,
)
async def get_webhook(
    webhook_id: UUID,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[WebhookEndpointService, Depends(get_webhook_endpoint_service)],
) -> WebhookEndpointResponse:
    """Get one registered webhook endpoint."""
    endpoint = await service.get(project.id, webhook_id)
    return WebhookEndpointResponse.from_entity(endpoint)


@router.patch(
    "/projects/{project_id}/webhooks/{webhook_id}",
    response_model=WebhookEndpointResponse,
)
async def update_webhook(
    webhook_id: UUID,
    payload: WebhookEndpointUpdateRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[WebhookEndpointService, Depends(get_webhook_endpoint_service)],
) -> WebhookEndpointResponse:
    """Change an endpoint's URL and/or subscriptions."""
    endpoint = await service.update(
        project_id=project.id,
        webhook_id=webhook_id,
        url=str(payload.url) if payload.url is not None else None,
        events=payload.events,
    )
    return WebhookEndpointResponse.from_entity(endpoint)


@router.delete(
    "/projects/{project_id}/webhooks/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_webhook(
    webhook_id: UUID,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[WebhookEndpointService, Depends(get_webhook_endpoint_service)],
) -> Response:
    """Delete an endpoint; queued callbacks to it are not retried afterwards."""
    await service.delete(project.id, webhook_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
