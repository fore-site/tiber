"""Project-scoped recipient APIs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ...application.services.recipient_query import RecipientQueryService
from ...infrastructure.models import ProjectModel
from ..dependencies import (
    enforce_authenticated_rate_limit,
    get_authenticated_project,
    get_recipient_query_service,
)
from ..schemas.recipient import RecipientListResponse, RecipientResponse

router = APIRouter(
    prefix="/v1/projects/{project_id}/recipients",
    tags=["Recipients"],
    dependencies=[Depends(enforce_authenticated_rate_limit)],
)


@router.get("", response_model=RecipientListResponse)
async def list_recipients(
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[RecipientQueryService, Depends(get_recipient_query_service)],
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
