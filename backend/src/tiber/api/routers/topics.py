from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from ...application.services.notification_topic import NotificationTopicService
from ...infrastructure.models import ProjectModel
from ..dependencies import (
    enforce_authenticated_rate_limit,
    get_authenticated_project,
    get_notification_topic_service,
)
from ..schemas.topic import NotificationTopicCreateRequest, NotificationTopicResponse

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


@router.post(
    "/projects/{project_id}/topics",
    response_model=NotificationTopicResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_notification_topic(
    payload: NotificationTopicCreateRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        NotificationTopicService,
        Depends(get_notification_topic_service),
    ],
) -> NotificationTopicResponse:
    """Create a category topic in the authenticated project."""
    topic = await service.create(
        project_id=project.id,
        title=payload.title,
        category=payload.category,
    )
    return NotificationTopicResponse.from_entity(topic)
