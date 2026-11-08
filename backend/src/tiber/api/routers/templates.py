"""Project-scoped template and brand profile APIs."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from ...application.services.template_management import (
    BrandProfileManagementService,
    TemplateManagementService,
)
from ...domain.enums import DeliveryChannel
from ...infrastructure.models import ProjectModel
from ..dependencies import (
    enforce_authenticated_rate_limit,
    get_authenticated_project,
    get_brand_profile_management_service,
    get_template_management_service,
)
from ..schemas.notification import NotificationContentModel
from ..schemas.template import (
    BrandProfileCreateRequest,
    BrandProfileResponse,
    BrandProfileUpdateRequest,
    TemplateCreateRequest,
    TemplatePresetResponse,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TemplateResponse,
    TemplateUpdateRequest,
)

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
        brand_profile_id=payload.brand_profile_id,
    )
    return TemplateResponse.from_entity(template)


@router.get(
    "/projects/{project_id}/templates",
    response_model=list[TemplateResponse],
)
async def list_templates(
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        TemplateManagementService, Depends(get_template_management_service)
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    channel: DeliveryChannel | None = None,
) -> list[TemplateResponse]:
    """List project templates, optionally filtered by delivery channel."""
    templates = await service.list(
        project.id,
        limit=limit,
        offset=offset,
        channel=channel,
    )
    return [TemplateResponse.from_entity(template) for template in templates]


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
    """Replace a template's variants, name, and brand profile."""
    template = await service.update(
        project_id=project.id,
        template_id=template_id,
        name=payload.name,
        variants=[variant.to_domain() for variant in payload.variants],
        brand_profile_id=payload.brand_profile_id,
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


@router.post(
    "/projects/{project_id}/brand-profiles",
    response_model=BrandProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_brand_profile(
    payload: BrandProfileCreateRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        BrandProfileManagementService, Depends(get_brand_profile_management_service)
    ],
) -> BrandProfileResponse:
    """Create reusable design tokens for a project."""
    profile = await service.create(
        project_id=project.id,
        name=payload.name,
        tokens=payload.tokens,
    )
    return BrandProfileResponse.from_entity(profile)


@router.get(
    "/projects/{project_id}/brand-profiles",
    response_model=list[BrandProfileResponse],
)
async def list_brand_profiles(
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        BrandProfileManagementService, Depends(get_brand_profile_management_service)
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BrandProfileResponse]:
    """List project brand profiles."""
    profiles = await service.list(project.id, limit=limit, offset=offset)
    return [BrandProfileResponse.from_entity(profile) for profile in profiles]


@router.get(
    "/projects/{project_id}/brand-profiles/{profile_id}",
    response_model=BrandProfileResponse,
)
async def get_brand_profile(
    profile_id: UUID,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        BrandProfileManagementService, Depends(get_brand_profile_management_service)
    ],
) -> BrandProfileResponse:
    """Get one project brand profile."""
    profile = await service.get(project.id, profile_id)
    return BrandProfileResponse.from_entity(profile)


@router.put(
    "/projects/{project_id}/brand-profiles/{profile_id}",
    response_model=BrandProfileResponse,
)
async def update_brand_profile(
    profile_id: UUID,
    payload: BrandProfileUpdateRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        BrandProfileManagementService, Depends(get_brand_profile_management_service)
    ],
) -> BrandProfileResponse:
    """Replace a project's brand profile."""
    profile = await service.update(
        project_id=project.id,
        profile_id=profile_id,
        name=payload.name,
        tokens=payload.tokens,
    )
    return BrandProfileResponse.from_entity(profile)


@router.delete(
    "/projects/{project_id}/brand-profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_brand_profile(
    profile_id: UUID,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        BrandProfileManagementService, Depends(get_brand_profile_management_service)
    ],
) -> Response:
    """Delete one profile; linked templates remain valid but unbranded."""
    await service.delete(project.id, profile_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
