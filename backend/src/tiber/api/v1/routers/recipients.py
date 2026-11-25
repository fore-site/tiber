"""Project-scoped recipient APIs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from tiber.api.common.dependencies import (
    enforce_authenticated_rate_limit,
    get_authenticated_project,
    get_recipient_management_service,
)
from tiber.api.v1.schemas.recipient import (
    RecipientCreateRequest,
    RecipientListResponse,
    RecipientPreferencesRequest,
    RecipientResponse,
    RecipientUpdateRequest,
)
from tiber.application.services.recipient_management import RecipientManagementService
from tiber.infrastructure.models import ProjectModel

router = APIRouter(
    prefix="/projects/{project_id}/recipients",
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
        timezone=payload.timezone,
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
    recipient: Annotated[str | None, Query(max_length=255)] = None,
) -> RecipientListResponse:
    """List project recipients; ``recipient`` narrows to one external ID."""
    page = await service.list(
        project.id,
        limit=limit,
        cursor=cursor,
        external_id=recipient,
    )
    return RecipientListResponse(
        data=[RecipientResponse.from_entity(recipient) for recipient in page.items],
        next_cursor=page.next_cursor,
    )


@router.patch("", response_model=RecipientResponse)
async def update_recipient(
    payload: RecipientUpdateRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        RecipientManagementService, Depends(get_recipient_management_service)
    ],
    recipient: Annotated[str, Query(min_length=1, max_length=255)],
) -> RecipientResponse:
    """Replace a recipient's address book and timezone, by external ID."""
    updated = await service.update_by_external_id(
        project_id=project.id,
        external_id=recipient,
        addresses=payload.addresses,
        timezone=payload.timezone_update(),
    )
    return RecipientResponse.from_entity(updated)


@router.put("/preferences", response_model=RecipientResponse)
async def update_recipient_preferences(
    payload: RecipientPreferencesRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        RecipientManagementService, Depends(get_recipient_management_service)
    ],
    recipient: Annotated[str, Query(min_length=1, max_length=255)],
) -> RecipientResponse:
    """Update a recipient's delivery preferences, addressed by external ID."""
    updated = await service.update_preferences_by_external_id(
        project_id=project.id,
        external_id=recipient,
        opted_out_channels=payload.opted_out_channels,
        unsubscribed_categories=payload.unsubscribed_categories,
        unsubscribed_topics=payload.unsubscribed_topics,
        blackout_period=payload.blackout_period_update(),
        quiet_hours=payload.quiet_hours_update(),
    )
    return RecipientResponse.from_entity(updated)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipient(
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        RecipientManagementService, Depends(get_recipient_management_service)
    ],
    recipient: Annotated[str, Query(min_length=1, max_length=255)],
) -> Response:
    """Delete a recipient by external ID."""
    await service.delete_by_external_id(
        project_id=project.id,
        external_id=recipient,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
