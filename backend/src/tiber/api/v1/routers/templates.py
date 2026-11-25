"""Project-scoped template APIs."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from tiber.api.common.dependencies import (
    enforce_authenticated_rate_limit,
    get_authenticated_project,
    get_template_management_service,
)
from tiber.api.v1.schemas.notification import NotificationContentModel
from tiber.api.v1.schemas.template import (
    TemplateContentPreviewRequest,
    TemplateCreateRequest,
    TemplatePageResponse,
    TemplatePresetResponse,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TemplateResponse,
    TemplateUpdateRequest,
)
from tiber.application.services.template_management import TemplateManagementService
from tiber.domain.enums import DeliveryChannel
from tiber.infrastructure.models import ProjectModel

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


@router.get(
    "/projects/{project_id}/template-presets",
    response_model=list[TemplatePresetResponse],
)
async def list_template_presets(
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        TemplateManagementService, Depends(get_template_management_service)
    ],
) -> list[TemplatePresetResponse]:
    """List selectable starter variants for a project."""
    del project
    return [TemplatePresetResponse.from_preset(preset) for preset in service.presets()]


@router.post(
    "/projects/{project_id}/templates",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    payload: TemplateCreateRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        TemplateManagementService, Depends(get_template_management_service)
    ],
) -> TemplateResponse:
    """Create a template with variants or from a selectable starter."""
    template = await service.create(
        project_id=project.id,
        name=payload.name,
        variants=(
            [variant.to_domain() for variant in payload.variants]
            if payload.variants is not None
            else None
        ),
        preset_id=payload.preset_id,
    )
    return TemplateResponse.from_entity(template)


@router.post(
    "/projects/{project_id}/templates/preview",
    response_model=TemplatePreviewResponse,
)
async def preview_template_content(
    payload: TemplateContentPreviewRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        TemplateManagementService, Depends(get_template_management_service)
    ],
) -> TemplatePreviewResponse:
    """Render unsaved editor content; nothing is persisted.

    This is the draft counterpart to ``/templates/{template_id}/preview``: the
    dashboard sends the content currently in the editor, the same Liquid engine
    used for delivery renders it, and the result is returned.

    Clients must still sandbox the returned HTML: templates are authored by the
    project and are not sanitized server-side.
    """
    del project  # authenticated by the dependency; nothing project-scoped is read
    preview = service.preview_content(
        channel=payload.channel,
        content=payload.content.to_domain(),
        variables=payload.variables,
    )
    return TemplatePreviewResponse(
        channel=payload.channel,
        content=NotificationContentModel(**preview.content.to_dict()),
        required_variables=sorted(preview.required_variables),
    )


@router.get(
    "/projects/{project_id}/templates",
    response_model=TemplatePageResponse,
)
async def list_templates(
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        TemplateManagementService, Depends(get_template_management_service)
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    channel: DeliveryChannel | None = None,
) -> TemplatePageResponse:
    """List one page of project templates, optionally filtered by channel."""
    page = await service.list(
        project.id,
        limit=limit,
        cursor=cursor,
        channel=channel,
    )
    return TemplatePageResponse(
        data=[TemplateResponse.from_entity(template) for template in page.items],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/projects/{project_id}/templates/{template_id}",
    response_model=TemplateResponse,
)
async def get_template(
    template_id: UUID,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        TemplateManagementService, Depends(get_template_management_service)
    ],
) -> TemplateResponse:
    """Get one project template."""
    template = await service.get(project.id, template_id)
    return TemplateResponse.from_entity(template)


@router.put(
    "/projects/{project_id}/templates/{template_id}",
    response_model=TemplateResponse,
)
async def update_template(
    template_id: UUID,
    payload: TemplateUpdateRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        TemplateManagementService, Depends(get_template_management_service)
    ],
) -> TemplateResponse:
    """Replace a template's variants and name."""
    template = await service.update(
        project_id=project.id,
        template_id=template_id,
        name=payload.name,
        variants=[variant.to_domain() for variant in payload.variants],
    )
    return TemplateResponse.from_entity(template)


@router.delete(
    "/projects/{project_id}/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_template(
    template_id: UUID,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        TemplateManagementService, Depends(get_template_management_service)
    ],
) -> Response:
    """Delete one project template."""
    await service.delete(project.id, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/templates/{template_id}/preview",
    response_model=TemplatePreviewResponse,
)
async def preview_template(
    template_id: UUID,
    payload: TemplatePreviewRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        TemplateManagementService, Depends(get_template_management_service)
    ],
) -> TemplatePreviewResponse:
    """Render a template preview; clients must sandbox returned HTML."""
    preview = await service.preview(
        project_id=project.id,
        template_id=template_id,
        channel=payload.channel,
        variables=payload.variables,
    )
    return TemplatePreviewResponse(
        channel=payload.channel,
        content=NotificationContentModel(**preview.content.to_dict()),
        required_variables=sorted(preview.required_variables),
    )
