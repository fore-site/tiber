"""Project-owned sender identity management."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from tiber.api.common.dependencies import (
    enforce_authenticated_rate_limit,
    get_active_authenticated_project,
    get_sender_identity_service,
)
from tiber.api.v1.schemas.sender_identity import (
    SenderIdentityCreateRequest,
    SenderIdentityListResponse,
    SenderIdentityResponse,
)
from tiber.application.services.sender_identity import SenderIdentityService
from tiber.infrastructure.models import ProjectModel

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


@router.post(
    "/projects/{project_id}/senders",
    response_model=SenderIdentityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_sender(
    payload: SenderIdentityCreateRequest,
    project: Annotated[ProjectModel, Depends(get_active_authenticated_project)],
    service: Annotated[SenderIdentityService, Depends(get_sender_identity_service)],
) -> SenderIdentityResponse:
    """Register a sending domain and return the DNS records to configure."""
    identity = await service.register(
        project_id=project.id,
        from_email=str(payload.from_email),
        display_name=payload.display_name,
        reply_to=str(payload.reply_to) if payload.reply_to is not None else None,
    )
    return SenderIdentityResponse.from_entity(identity)


@router.get(
    "/projects/{project_id}/senders",
    response_model=SenderIdentityListResponse,
)
async def list_senders(
    project: Annotated[ProjectModel, Depends(get_active_authenticated_project)],
    service: Annotated[SenderIdentityService, Depends(get_sender_identity_service)],
) -> SenderIdentityListResponse:
    """List the project's sender identities.

    An empty list means email delivery uses the Tiber fallback sender.
    """
    identities = await service.list(project.id)
    return SenderIdentityListResponse(
        data=[SenderIdentityResponse.from_entity(identity) for identity in identities]
    )


@router.post(
    "/projects/{project_id}/senders/{sender_id}/verification",
    response_model=SenderIdentityResponse,
)
async def verify_sender(
    sender_id: UUID,
    project: Annotated[ProjectModel, Depends(get_active_authenticated_project)],
    service: Annotated[SenderIdentityService, Depends(get_sender_identity_service)],
) -> SenderIdentityResponse:
    """Ask the provider to verify the sender domain and return its current state."""
    identity = await service.verify(project.id, sender_id)
    return SenderIdentityResponse.from_entity(identity)


@router.delete(
    "/projects/{project_id}/senders/{sender_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_sender(
    sender_id: UUID,
    project: Annotated[ProjectModel, Depends(get_active_authenticated_project)],
    service: Annotated[SenderIdentityService, Depends(get_sender_identity_service)],
) -> Response:
    """Remove the sender domain and fall back to the Tiber sender."""
    await service.delete(project.id, sender_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
