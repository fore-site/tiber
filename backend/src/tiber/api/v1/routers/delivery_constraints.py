"""Project-scoped delivery-constraint APIs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from tiber.api.common.dependencies import (
    enforce_authenticated_rate_limit,
    get_authenticated_project,
    get_delivery_constraint_management_service,
)
from tiber.api.v1.schemas.delivery_constraint import (
    DeliveryConstraintResponse,
    DeliveryConstraintUpdateRequest,
)
from tiber.application.services.delivery_constraint_management import (
    DeliveryConstraintManagementService,
)
from tiber.infrastructure.models import ProjectModel

router = APIRouter(
    prefix="/projects/{project_id}/delivery-constraint",
    tags=["Delivery constraints"],
    dependencies=[Depends(enforce_authenticated_rate_limit)],
)


@router.get("", response_model=DeliveryConstraintResponse)
async def get_delivery_constraint(
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        DeliveryConstraintManagementService,
        Depends(get_delivery_constraint_management_service),
    ],
) -> DeliveryConstraintResponse:
    """Return the project's delivery constraint, or its permissive default."""
    constraint = await service.get(project.id)
    return DeliveryConstraintResponse.from_entity(constraint)


@router.put("", response_model=DeliveryConstraintResponse)
async def replace_delivery_constraint(
    payload: DeliveryConstraintUpdateRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        DeliveryConstraintManagementService,
        Depends(get_delivery_constraint_management_service),
    ],
) -> DeliveryConstraintResponse:
    """Replace the project's whole delivery constraint."""
    constraint = await service.replace(
        project_id=project.id,
        blackout_periods=[period.to_domain() for period in payload.blackout_periods],
        quiet_hours=[window.to_domain() for window in payload.quiet_hours],
        timezone=payload.timezone,
    )
    return DeliveryConstraintResponse.from_entity(constraint)
