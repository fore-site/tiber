"""Dashboard project APIs."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from ...application.auth import AuthAccount
from ...application.services.project_management import ProjectManagementService
from ..dependencies import (
    enforce_dashboard_rate_limit,
    get_current_account,
    get_project_management_service,
)
from ..schemas.project import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)

router = APIRouter(
    prefix="/projects",
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


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    account: Annotated[AuthAccount, Depends(get_current_account)],
    service: Annotated[
        ProjectManagementService, Depends(get_project_management_service)
    ],
) -> ProjectResponse:
    """Create a project owned by the authenticated account."""
    project = await service.create(
        account_id=account.id,
        name=payload.name,
        description=payload.description,
    )
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    account: Annotated[AuthAccount, Depends(get_current_account)],
    service: Annotated[
        ProjectManagementService, Depends(get_project_management_service)
    ],
) -> ProjectResponse:
    """Get one project owned by the authenticated account."""
    project = await service.get(account_id=account.id, project_id=project_id)
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    account: Annotated[AuthAccount, Depends(get_current_account)],
    service: Annotated[
        ProjectManagementService, Depends(get_project_management_service)
    ],
) -> ProjectResponse:
    """Update the supplied project fields, leaving omitted fields unchanged."""
    current = await service.get(account_id=account.id, project_id=project_id)
    fields = payload.model_fields_set
    project = await service.update(
        account_id=account.id,
        project_id=project_id,
        name=payload.name if "name" in fields else current.name,
        description=(
            payload.description if "description" in fields else current.description
        ),
    )
    return ProjectResponse.model_validate(project)


@router.post("/{project_id}/restore", response_model=ProjectResponse)
async def restore_project(
    project_id: UUID,
    account: Annotated[AuthAccount, Depends(get_current_account)],
    service: Annotated[
        ProjectManagementService, Depends(get_project_management_service)
    ],
) -> ProjectResponse:
    """Restore a soft-deleted project within its 90-day grace period."""
    project = await service.restore(account_id=account.id, project_id=project_id)
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    account: Annotated[AuthAccount, Depends(get_current_account)],
    service: Annotated[
        ProjectManagementService, Depends(get_project_management_service)
    ],
) -> Response:
    """Soft-delete a project; Tiber purges it after the grace period."""
    await service.delete(account_id=account.id, project_id=project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
