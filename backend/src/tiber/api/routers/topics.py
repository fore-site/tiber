from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from ...application.services.notification_topic import NotificationTopicService
from ...infrastructure.models import ProjectModel
from ..dependencies import (
    enforce_authenticated_rate_limit,
    get_authenticated_project,
    get_notification_topic_service,
)
from ..schemas.topic import (
    NotificationTopicCreateRequest,
    NotificationTopicListResponse,
    NotificationTopicResponse,
)

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


@router.get(
    "/projects/{project_id}/topics",
    response_model=NotificationTopicListResponse,
)
async def list_notification_topics(
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[
        NotificationTopicService,
        Depends(get_notification_topic_service),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> NotificationTopicListResponse:
    """List one page of the authenticated project's topics, newest first."""
    page = await service.list(project.id, limit=limit, cursor=cursor)
    return NotificationTopicListResponse(
        data=[NotificationTopicResponse.from_entity(topic) for topic in page.items],
        next_cursor=page.next_cursor,
    )
