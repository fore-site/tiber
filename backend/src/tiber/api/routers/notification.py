from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)

from ...application.services.notification_intake import NotificationIntakeService
from ...application.services.notification_query import NotificationQueryService
from ...infrastructure.models import ProjectModel
from ...infrastructure.rate_limit.ingestion_rate_limiter import IngestionRateLimiter
from ..dependencies import (
    get_authenticated_project,
    get_ingestion_rate_limiter,
    get_notification_intake_service,
    get_notification_query_service,
)
from ..mappers.notification_intake import to_accept_command
from ..schemas.intake import IntakeStatusResponse
from ..schemas.notification import (
    NotificationCreateRequest,
    NotificationCreateResponse,
    NotificationResponse,
)

router = APIRouter()


@router.post(
    "/projects/{project_id}/notifications",
    response_model=NotificationCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_notification(
    payload: NotificationCreateRequest,
    project: Annotated[
        ProjectModel,
        Depends(get_authenticated_project),
    ],
    service: Annotated[
        NotificationIntakeService,
        Depends(get_notification_intake_service),
    ],
    limiter: Annotated[
        IngestionRateLimiter,
        Depends(get_ingestion_rate_limiter),
    ],
    request: Request,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1),
    ],
) -> NotificationCreateResponse:
    """Accept a notification request.

    Everything that can be acted on is validated before this returns, so a 202 means
    the request is valid and queued. The notifications themselves (one per
    channel) are created asynchronously; follow the ``Location`` header, or
    ``GET /projects/{project_id}/notification-requests/{correlation_id}``, to
    see them.

    Requires an ``Idempotency-Key`` header. Repeating a request with the same key
    and the same body returns the same ``correlation_id`` (with an
    ``Idempotent-Replayed: true`` header). Reusing a key with a different body
    is rejected with ``409``.

    Ingestion is rate-limited per project: once the project's windowed quota is
    exhausted the request is rejected with ``429 Too Many Requests``.
    """
    if not await limiter.is_allowed(project.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Ingestion rate limit exceeded.",
        )

    # The batch handle (``correlation_id``) is generated server-side by the
    # intake. It is deliberately NOT the X-Correlation-ID tracing header, which
    # clients may reuse across requests or send in a non-UUID form.
    accepted = await service.accept(
        to_accept_command(
            payload,
            project_id=project.id,
            idempotency_key=idempotency_key,
        )
    )

    response.headers["Location"] = str(
        request.app.url_path_for(
            "get_notification_request",
            project_id=accepted.project_id,
            correlation_id=accepted.correlation_id,
        )
    )
    if accepted.replayed:
        response.headers["Idempotent-Replayed"] = "true"

    return NotificationCreateResponse.from_input(
        accepted.project_id, accepted.correlation_id
    )


@router.get(
    "/projects/{project_id}/notification-requests/{correlation_id}",
    name="get_notification_request",
    response_model=IntakeStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_notification_request(
    project: Annotated[
        ProjectModel,
        Depends(get_authenticated_project),
    ],
    correlation_id: UUID,
    service: Annotated[
        NotificationQueryService,
        Depends(get_notification_query_service),
    ],
) -> IntakeStatusResponse:
    """Status of an accepted request and the notifications it produced.

    ``status`` is ``received`` or ``processing`` while the request is being
    expanded (``notifications`` is empty), ``completed`` once every channel has
    its notification, and ``failed`` if processing could not finish.
    """
    view = await service.get_request_status(project.id, correlation_id)
    return IntakeStatusResponse.from_intake(
        view.intake, view.notifications, view.recipient
    )


@router.get(
    "/projects/{project_id}/notifications/{notification_id}",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
)
async def get_notification(
    project: Annotated[
        ProjectModel,
        Depends(get_authenticated_project),
    ],
    notification_id: UUID,
    service: Annotated[
        NotificationQueryService,
        Depends(get_notification_query_service),
    ],
) -> NotificationResponse:
    """Retrieve a notification by its ID."""
    notification = await service.get_notification(project.id, notification_id)
    # recipient_id and the template/topic slugs are not resolved on this path yet.
    return NotificationResponse.from_entity(notification)


@router.get(
    "/projects/{project_id}/notifications",
    response_model=list[NotificationResponse],
    status_code=status.HTTP_200_OK,
)
async def list_notifications(
    project: Annotated[
        ProjectModel,
        Depends(get_authenticated_project),
    ],
    service: Annotated[
        NotificationQueryService,
        Depends(get_notification_query_service),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NotificationResponse]:
    """List notifications for a project (most recent first is not yet ordered)."""
    notifications = await service.list_notifications(project.id, limit, offset)
    return [NotificationResponse.from_entity(n) for n in notifications]


@router.put(
    "/projects/{project_id}/notifications/{notification_id}/cancellation",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_notification(
    project: Annotated[
        ProjectModel,
        Depends(get_authenticated_project),
    ],
    notification_id: UUID,
) -> None:
    """Cancel a scheduled notification.

    Requires repository update semantics via the immutable entity transition;
    TODO: wire ``Notification.mark_cancelled()`` through the repository.
    """
    raise NotImplementedError
