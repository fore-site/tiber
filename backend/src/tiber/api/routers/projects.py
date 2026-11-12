"""Dashboard project APIs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ...application.auth import AuthAccount
from ...application.services.project_management import ProjectManagementService
from ..dependencies import (
    enforce_dashboard_rate_limit,
    get_current_account,
    get_project_management_service,
)
from ..schemas.project import ProjectListResponse, ProjectResponse

router = APIRouter(
    prefix="/v1/projects",
    tags=["Projects"],
    dependencies=[Depends(enforce_dashboard_rate_limit)],
)


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    account: Annotated[AuthAccount, Depends(get_current_account)],
    service: Annotated[
        ProjectManagementService, Depends(get_project_management_service)
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> ProjectListResponse:
    """List one page of projects owned by the authenticated account."""
    page = await service.list(account_id=account.id, limit=limit, cursor=cursor)
    return ProjectListResponse(
        data=[ProjectResponse.model_validate(project) for project in page.items],
        next_cursor=page.next_cursor,
    )
