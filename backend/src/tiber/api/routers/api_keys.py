from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ...application.auth import AuthAccount
from ...application.services.api_key_management import (
    APIKeyManagementError,
    APIKeyManagementService,
)
from ..dependencies import (
    enforce_dashboard_rate_limit,
    get_api_key_management_service,
    get_current_account,
)
from ..schemas.auth import (
    APIKeyCreateRequest,
    APIKeyListResponse,
    APIKeyResponse,
    APIKeyWithSecretResponse,
    PaginationMeta,
)

router = APIRouter(prefix="/v1/projects/{project_id}/api-keys", tags=["API Keys"])


def _http_error(exc: APIKeyManagementError) -> HTTPException:
    errors = {
        "project_not_found": (status.HTTP_404_NOT_FOUND, "Project not found."),
        "api_key_not_found": (status.HTTP_404_NOT_FOUND, "API key not found."),
        "api_key_state_unavailable": (
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "API-key revocation state is unavailable.",
        ),
    }
    status_code, detail = errors[exc.code]
    return HTTPException(status_code=status_code, detail=detail)


def _response(key) -> APIKeyResponse:
    return APIKeyResponse(
        id=key.id,
        project_id=key.project_id,
        name=key.name,
        prefix=key.key_prefix,
        last_used_at=None,
        created_at=key.created_at,
        revoked_at=key.revoked_at,
        expires_at=key.expires_at,
    )


@router.post(
    "",
    response_model=APIKeyWithSecretResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_dashboard_rate_limit)],
)
async def create_api_key(
    project_id: UUID,
    payload: APIKeyCreateRequest,
    account: Annotated[AuthAccount, Depends(get_current_account)],
    service: Annotated[
        APIKeyManagementService, Depends(get_api_key_management_service)
    ],
) -> APIKeyWithSecretResponse:
    """Create a project-scoped key and return its secret exactly once."""
    try:
        key, secret = await service.create(
            project_id=project_id,
            account_id=account.id,
            name=payload.name,
        )
    except APIKeyManagementError as exc:
        raise _http_error(exc) from exc
    return APIKeyWithSecretResponse(**_response(key).model_dump(), key=secret)


@router.get(
    "",
    response_model=APIKeyListResponse,
    dependencies=[Depends(enforce_dashboard_rate_limit)],
)
async def list_api_keys(
    project_id: UUID,
    account: Annotated[AuthAccount, Depends(get_current_account)],
    service: Annotated[
        APIKeyManagementService, Depends(get_api_key_management_service)
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> APIKeyListResponse:
    """List project key metadata without exposing credential hashes."""
    try:
        page = await service.list(
            project_id=project_id,
            account_id=account.id,
            limit=limit,
            offset=offset,
        )
    except APIKeyManagementError as exc:
        raise _http_error(exc) from exc
    return APIKeyListResponse(
        data=[_response(key) for key in page.keys],
        meta=PaginationMeta(
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        ),
    )


@router.get(
    "/{key_id}",
    response_model=APIKeyResponse,
    dependencies=[Depends(enforce_dashboard_rate_limit)],
)
async def get_api_key(
    project_id: UUID,
    key_id: UUID,
    account: Annotated[AuthAccount, Depends(get_current_account)],
    service: Annotated[
        APIKeyManagementService, Depends(get_api_key_management_service)
    ],
) -> APIKeyResponse:
    """Retrieve one key's metadata within its owning project."""
    try:
        key = await service.get(
            project_id=project_id,
            account_id=account.id,
            key_id=key_id,
        )
    except APIKeyManagementError as exc:
        raise _http_error(exc) from exc
    return _response(key)


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_dashboard_rate_limit)],
)
async def revoke_api_key(
    project_id: UUID,
    key_id: UUID,
    account: Annotated[AuthAccount, Depends(get_current_account)],
    service: Annotated[
        APIKeyManagementService, Depends(get_api_key_management_service)
    ],
) -> Response:
    """Revoke a project key and remove its cached authentication facts."""
    try:
        await service.revoke(
            project_id=project_id,
            account_id=account.id,
            key_id=key_id,
        )
    except APIKeyManagementError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
