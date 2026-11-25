"""Project-scoped engagement event reporting and queries.

Provider-reported events enter through the internal provider webhook path, not
here. This router exposes client-reported events (push opens and clicks) and
the read side for analytics.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from tiber.api.common.dependencies import (
    enforce_authenticated_rate_limit,
    get_authenticated_project,
    get_engagement_event_service,
)
from tiber.api.v1.schemas.engagement_event import (
    EngagementEventPageResponse,
    EngagementEventReportRequest,
    EngagementEventResponse,
)
from tiber.application.services.engagement_event import EngagementEventService
from tiber.domain.enums import DeliveryChannel, EngagementEventType
from tiber.infrastructure.models import ProjectModel

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


@router.get(
    "/projects/{project_id}/engagement-events",
    response_model=EngagementEventPageResponse,
)
async def list_engagement_events(
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[EngagementEventService, Depends(get_engagement_event_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    event_type: EngagementEventType | None = None,
    recipient_id: UUID | None = None,
    notification_id: UUID | None = None,
    channel: DeliveryChannel | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
) -> EngagementEventPageResponse:
    """List a page of a project's engagement events, newest first."""
    _require_ordered_window(occurred_after, occurred_before)
    page = await service.list(
        project.id,
        limit=limit,
        cursor=cursor,
        event_type=event_type,
        recipient_id=recipient_id,
        notification_id=notification_id,
        channel=channel,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
    )
    return EngagementEventPageResponse(
        data=[EngagementEventResponse.from_entity(event) for event in page.items],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/projects/{project_id}/engagement-events/{event_id}",
    response_model=EngagementEventResponse,
)
async def get_engagement_event(
    event_id: UUID,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[EngagementEventService, Depends(get_engagement_event_service)],
) -> EngagementEventResponse:
    """Get one engagement event."""
    event = await service.get(project.id, event_id)
    return EngagementEventResponse.from_entity(event)


@router.get(
    "/projects/{project_id}/notifications/{notification_id}/engagement-events",
    response_model=EngagementEventPageResponse,
)
async def list_notification_engagement_events(
    notification_id: UUID,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[EngagementEventService, Depends(get_engagement_event_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    event_type: EngagementEventType | None = None,
) -> EngagementEventPageResponse:
    """List a page of the engagement events recorded for one notification."""
    page = await service.list(
        project.id,
        limit=limit,
        cursor=cursor,
        event_type=event_type,
        notification_id=notification_id,
    )
    return EngagementEventPageResponse(
        data=[EngagementEventResponse.from_entity(event) for event in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/projects/{project_id}/notifications/{notification_id}/engagement-events",
    response_model=EngagementEventResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Replay of an already-recorded event (same Idempotency-Key "
                "and payload)."
            ),
            "headers": {
                "Idempotent-Replayed": {
                    "description": "Present and true when the event was replayed.",
                    "schema": {"type": "string", "enum": ["true"]},
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {"description": "Notification not found."},
        status.HTTP_409_CONFLICT: {
            "description": (
                "The Idempotency-Key was already used with a different payload."
            )
        },
    },
)
async def report_engagement_event(
    notification_id: UUID,
    payload: EngagementEventReportRequest,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    service: Annotated[EngagementEventService, Depends(get_engagement_event_service)],
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
) -> EngagementEventResponse:
    """Record a client-reported push or in-app interaction.

    Recipient and channel are read from the stored notification, so a client
    cannot attribute an event to a recipient it does not own. Email and SMS
    engagement is provider-reported and rejected here.

    Requires an ``Idempotency-Key`` header. Repeating the request with the same
    key and payload returns the original event with ``200`` and
    ``Idempotent-Replayed: true``; reusing the key for a different payload is
    rejected with ``409``.
    """
    recorded = await service.record(
        project_id=project.id,
        notification_id=notification_id,
        event_type=payload.event_type,
        occurred_at=payload.occurred_at,
        metadata=payload.metadata,
        idempotency_key=idempotency_key,
    )
    if not recorded.created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return EngagementEventResponse.from_entity(recorded.event)


def _require_ordered_window(
    occurred_after: datetime | None, occurred_before: datetime | None
) -> None:
    """Reject an inverted time window instead of returning a silent empty list."""
    if (
        occurred_after is not None
        and occurred_before is not None
        and occurred_after > occurred_before
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`occurred_after` must not be later than `occurred_before`.",
        )
