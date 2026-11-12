"""Project-scoped recipient APIs."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from ...application.services.recipient_management import RecipientManagementService
from ...infrastructure.models import ProjectModel
from ..dependencies import (
    enforce_authenticated_rate_limit,
    get_authenticated_project,
    get_recipient_management_service,
)
from ..schemas.recipient import (
    RecipientCreateRequest,
    RecipientListResponse,
    RecipientResponse,
    RecipientUpdateRequest,
)

router = APIRouter(
    prefix="/v1/projects/{project_id}/recipients",
    tags=["Recipients"],
    dependencies=[Depends(enforce_authenticated_rate_limit)],
)


@router.post("", response_model=RecipientResponse, status_code=status.HTTP_201_CREATED)
async def create_recipient(
    payload: RecipientCreateRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        RecipientManagementService, Depends(get_recipient_management_service)
    ],
) -> RecipientResponse:
    """Register a recipient in the authenticated project."""
    recipient = await service.create(
        project_id=project.id,
        external_id=payload.external_id,
        addresses=payload.addresses,
    )
    return RecipientResponse.from_entity(recipient)


@router.get("", response_model=RecipientListResponse)
async def list_recipients(
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        RecipientManagementService, Depends(get_recipient_management_service)
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    external_id: Annotated[str | None, Query(max_length=255)] = None,
) -> RecipientListResponse:
    """List one page of project recipients, newest first."""
    page = await service.list(
        project.id,
        limit=limit,
        cursor=cursor,
        external_id=external_id,
    )
    return RecipientListResponse(
        data=[RecipientResponse.from_entity(recipient) for recipient in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/{recipient_id}", response_model=RecipientResponse)
async def get_recipient(
    recipient_id: UUID,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        RecipientManagementService, Depends(get_recipient_management_service)
    ],
) -> RecipientResponse:
    """Get one recipient in the authenticated project."""
    recipient = await service.get(project.id, recipient_id)
    return RecipientResponse.from_entity(recipient)


@router.patch("/{recipient_id}", response_model=RecipientResponse)
async def update_recipient(
    recipient_id: UUID,
    payload: RecipientUpdateRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        RecipientManagementService, Depends(get_recipient_management_service)
    ],
) -> RecipientResponse:
    """Replace a recipient's address book."""
    recipient = await service.update(
        project_id=project.id,
        recipient_id=recipient_id,
        addresses=payload.addresses,
    )
    return RecipientResponse.from_entity(recipient)


@router.delete("/{recipient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipient(
    recipient_id: UUID,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        RecipientManagementService, Depends(get_recipient_management_service)
    ],
    permanent: Annotated[bool, Query()] = False,
) -> Response:
    """Soft-delete a recipient, or permanently purge one already deleted."""
    await service.delete(
        project_id=project.id,
        recipient_id=recipient_id,
        permanent=permanent,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
