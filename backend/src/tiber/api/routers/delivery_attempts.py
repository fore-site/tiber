"""Project-scoped reads of the delivery attempt history.

Attempts are written by the worker delivery processor. They are exposed
read-only because history is the diagnostic record; editing it would make
failures unreconstructable.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ...application.services.delivery_attempt_query import DeliveryAttemptQueryService
from ...infrastructure.models import ProjectModel
from ..dependencies import (
    enforce_authenticated_rate_limit,
    get_authenticated_project,
    get_delivery_attempt_query_service,
)
from ..schemas.delivery_attempt import DeliveryAttemptResponse

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


@router.get(
    "/projects/{project_id}/notifications/{notification_id}/delivery-attempts",
    response_model=list[DeliveryAttemptResponse],
)
async def list_delivery_attempts(
    notification_id: UUID,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        DeliveryAttemptQueryService, Depends(get_delivery_attempt_query_service)
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DeliveryAttemptResponse]:
    """List a notification's delivery attempts in attempt order."""
    attempts = await service.list(
        project.id, notification_id, limit=limit, offset=offset
    )
    return [DeliveryAttemptResponse.from_entity(attempt) for attempt in attempts]


@router.get(
    "/projects/{project_id}/notifications/{notification_id}"
    "/delivery-attempts/{attempt_id}",
    response_model=DeliveryAttemptResponse,
)
async def get_delivery_attempt(
    notification_id: UUID,
    attempt_id: UUID,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        DeliveryAttemptQueryService, Depends(get_delivery_attempt_query_service)
    ],
) -> DeliveryAttemptResponse:
    """Get one delivery attempt."""
    attempt = await service.get(project.id, notification_id, attempt_id)
    return DeliveryAttemptResponse.from_entity(attempt)
