from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse

from ...application.auth import AuthAccount, AuthContext
from ...application.auth_tokens import IssuedTokens
from ...application.services.authentication import (
    AuthenticationOperationError,
    AuthenticationService,
)
from ..dependencies import (
    enforce_auth_rate_limit,
    enforce_dashboard_rate_limit,
    get_auth_context,
    get_authentication_service,
    get_current_account,
)
from ..schemas.auth import (
    AccountResponse,
    EmailRequest,
    EmailVerificationRequest,
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    RegistrationAcceptedResponse,
    TokenResponse,
    UpdateAccountRequest,
)

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


_ERRORS: dict[str, tuple[int, str | dict[str, str]]] = {
    "account_exists": (
        status.HTTP_409_CONFLICT,
        "An account with this email already exists.",
    ),
    "invalid_credentials": (
        status.HTTP_401_UNAUTHORIZED,
        "Invalid email or password.",
    ),
    "email_not_verified": (
        status.HTTP_403_FORBIDDEN,
        "Please verify your email address before signing in.",
    ),
    "invalid_refresh_token": (
        status.HTTP_401_UNAUTHORIZED,
        "Invalid or expired refresh token.",
    ),
    "invalid_access_token": (status.HTTP_401_UNAUTHORIZED, "Invalid access token."),
    "account_not_authorized": (
        status.HTTP_401_UNAUTHORIZED,
        "Account is not authorized.",
    ),
    "auth_state_unavailable": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Authentication state is unavailable.",
    ),
    "otp_not_configured": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Email verification is not configured.",
    ),
    "email_delivery_failed": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Authentication email could not be delivered.",
    ),
    "invalid_verification_code": (
        status.HTTP_401_UNAUTHORIZED,
        "Invalid, expired, or locked verification code.",
    ),
    "email_identity_conflict": (
        status.HTTP_409_CONFLICT,
        "This email address is already associated with another account.",
    ),
    "github_not_configured": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "GitHub OAuth is not configured.",
    ),
    "invalid_oauth_state": (
        status.HTTP_401_UNAUTHORIZED,
        "Invalid or expired OAuth state.",
    ),
    "authorization_rejected": (
        status.HTTP_401_UNAUTHORIZED,
        "GitHub authorization was rejected.",
    ),
    "provider_unavailable": (
        status.HTTP_502_BAD_GATEWAY,
        "GitHub authentication could not be completed.",
    ),
    "invalid_provider_response": (
        status.HTTP_502_BAD_GATEWAY,
        "GitHub returned an invalid authentication response.",
    ),
    "verified_email_required": (
        status.HTTP_401_UNAUTHORIZED,
        "GitHub must provide a verified email address.",
    ),
    "github_identity_conflict": (
        status.HTTP_409_CONFLICT,
        "This email is already linked to another GitHub account.",
    ),
    "no_password_set": (
        status.HTTP_400_BAD_REQUEST,
        {"error": "no_password_set"},
    ),
    "invalid_current_password": (
        status.HTTP_400_BAD_REQUEST,
        {"error": "invalid_current_password"},
    ),
    "invalid_password_reset_token": (
        status.HTTP_401_UNAUTHORIZED,
        "Invalid or expired password-reset token.",
    ),
    "api_key_state_unavailable": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "API-key revocation state is unavailable.",
    ),
    "jwt_not_configured": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "JWT signing is not configured.",
    ),
}


def _http_error(exc: AuthenticationOperationError) -> HTTPException:
    status_code, detail = _ERRORS[exc.code]
    return HTTPException(status_code=status_code, detail=detail)


def _token_response(tokens: IssuedTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


def _account_response(account: AuthAccount) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        email=account.email,
        role=account.role,
        is_verified=account.is_verified,
        pending_email=account.pending_email,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


@router.post(
    "/register",
    response_model=RegistrationAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def register(
    payload: RegisterRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> RegistrationAcceptedResponse:
    """Create an unverified email account and send its verification code."""
    try:
        await service.register(str(payload.email), payload.password)
    except AuthenticationOperationError as exc:
        raise _http_error(exc) from exc
    return RegistrationAcceptedResponse()


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def login(
    payload: LoginRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> TokenResponse:
    """Authenticate an email/password account and issue a token pair."""
    try:
        tokens = await service.login(str(payload.email), payload.password)
    except AuthenticationOperationError as exc:
        raise _http_error(exc) from exc
    return _token_response(tokens)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def refresh(
    payload: RefreshRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> TokenResponse:
    """Rotate a single-use refresh token."""
    try:
        tokens = await service.refresh(payload.refresh_token)
    except AuthenticationOperationError as exc:
        raise _http_error(exc) from exc
    return _token_response(tokens)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_dashboard_rate_limit)],
)
async def logout(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> Response:
    """Revoke the current JWT and its associated refresh-token session."""
    try:
        await service.logout(context)
    except AuthenticationOperationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=AccountResponse,
    dependencies=[Depends(enforce_dashboard_rate_limit)],
)
async def get_me(
    account: Annotated[AuthAccount, Depends(get_current_account)],
) -> AccountResponse:
    """Return the authenticated dashboard account profile."""
    return _account_response(account)


@router.patch(
    "/me",
    response_model=AccountResponse,
    dependencies=[Depends(enforce_dashboard_rate_limit)],
)
async def update_me(
    payload: UpdateAccountRequest,
    account: Annotated[AuthAccount, Depends(get_current_account)],
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> AccountResponse:
    """Start an email-change verification flow without changing the login email."""
    try:
        updated = await service.update_email(account.id, str(payload.email))
    except AuthenticationOperationError as exc:
        raise _http_error(exc) from exc
    return _account_response(updated)


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_dashboard_rate_limit)],
)
async def delete_me(
    account: Annotated[AuthAccount, Depends(get_current_account)],
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> Response:
    """Deactivate an account while preserving owned project history."""
    try:
        await service.deactivate(account.id)
    except AuthenticationOperationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/email/verify",
    response_model=TokenResponse,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def verify_email(
    payload: EmailVerificationRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> TokenResponse:
    """Consume an email code and verify registration or a pending email change."""
    try:
        tokens = await service.verify_email(str(payload.email), payload.otp)
    except AuthenticationOperationError as exc:
        raise _http_error(exc) from exc
    return _token_response(tokens)


@router.post(
    "/email/verify/resend",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def resend_verification(
    payload: EmailRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> Response:
    """Resend verification without disclosing whether the email is registered."""
    try:
        await service.resend_verification(str(payload.email))
    except AuthenticationOperationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.get(
    "/github",
    dependencies=[Depends(enforce_auth_rate_limit)],
    include_in_schema=True,
)
async def github_login(
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> RedirectResponse:
    """Start GitHub OAuth using a short-lived, single-use CSRF state."""
    try:
        authorization_url = await service.github_authorization_url()
    except AuthenticationOperationError as exc:
        raise _http_error(exc) from exc
    return RedirectResponse(
        authorization_url,
        status_code=status.HTTP_302_FOUND,
    )


@router.get(
    "/github/callback",
    response_model=TokenResponse,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def github_callback(
    code: Annotated[str, Query(min_length=1)],
    state: Annotated[str, Query(min_length=1)],
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> TokenResponse:
    """Validate OAuth state, resolve a verified GitHub email, and issue tokens."""
    try:
        tokens = await service.github_callback(code, state)
    except AuthenticationOperationError as exc:
        raise _http_error(exc) from exc
    return _token_response(tokens)


@router.post(
    "/password/change",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_dashboard_rate_limit)],
)
async def change_password(
    payload: PasswordChangeRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    account: Annotated[AuthAccount, Depends(get_current_account)],
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> Response:
    """Change a password and invalidate all older account sessions."""
    try:
        await service.change_password(
            account.id,
            payload.current_password,
            payload.new_password,
            context,
        )
    except AuthenticationOperationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password/reset-request",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def request_password_reset(
    payload: PasswordResetRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> Response:
    """Request a reset link while returning the same response for every email."""
    try:
        await service.request_password_reset(str(payload.email))
    except AuthenticationOperationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def reset_password(
    payload: PasswordResetConfirmRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> Response:
    """Consume a reset link and update the password hash."""
    try:
        await service.reset_password(payload.token, payload.password)
    except AuthenticationOperationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
