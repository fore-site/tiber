from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, Response, status
from jose.exceptions import JWTError
from pycurb.adapters.fastapi import rate_limiter
from pycurb.core import RateLimitResult
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..application.auth import ApiKeyAuthenticationError, AuthAccount, AuthContext
from ..application.ports.api_key_auth_cache import ApiKeyAuthCache
from ..application.ports.auth_email_sender import AuthEmailSender
from ..application.ports.intake import Outbox
from ..application.ports.unit_of_work import UnitOfWork
from ..application.services.api_key_authenticator import (
    ApiKeyAuthenticator,
    looks_like_api_key,
)
from ..application.services.api_key_management import APIKeyManagementService
from ..application.services.authentication import (
    AuthenticationOperationError,
    AuthenticationService,
)
from ..application.services.notification_cancellation import (
    NotificationCancellationService,
)
from ..application.services.notification_intake import NotificationIntakeService
from ..application.services.notification_query import NotificationQueryService
from ..application.services.recipient_resolution import RecipientResolutionService
from ..core.config import get_settings
from ..core.database import AsyncSessionFactory
from ..core.redis import RedisKeys, get_redis_client
from ..core.security import decode_token, hash_api_key
from ..domain.repositories import NotificationIntakeRepository
from ..infrastructure.cache.api_keys import RedisApiKeyAuthCache
from ..infrastructure.cache.jwt import JWTBlocklistStore
from ..infrastructure.models import ProjectModel
from ..infrastructure.providers.auth_email import HttpAuthEmailSender
from ..infrastructure.providers.github_oauth import HttpGitHubOAuthProvider
from ..infrastructure.rate_limit.policies import RateLimitPolicies
from ..infrastructure.repositories.sqlalchemy_api_key_repository import (
    SQLAlchemyAPIKeyRepository,
)
from ..infrastructure.repositories.sqlalchemy_auth_account_repository import (
    SQLAlchemyAuthAccountRepository,
)
from ..infrastructure.repositories.sqlalchemy_notification_intake_repository import (
    SQLAlchemyNotificationIntakeRepository,
)
from ..infrastructure.repositories.sqlalchemy_notification_repository import (
    SQLAlchemyNotificationRepository,
)
from ..infrastructure.repositories.sqlalchemy_notification_topic_repository import (
    SQLAlchemyNotificationTopicRepository,
)
from ..infrastructure.repositories.sqlalchemy_outbox import SQLAlchemyOutbox
from ..infrastructure.repositories.sqlalchemy_project_repository import (
    SQLAlchemyProjectRepository,
)
from ..infrastructure.repositories.sqlalchemy_recipient_repository import (
    SQLAlchemyRecipientRepository,
)
from ..infrastructure.repositories.sqlalchemy_template_repository import (
    SQLAlchemyTemplateRepository,
)
from ..infrastructure.repositories.unit_of_work import SqlAlchemyUnitOfWork

settings = get_settings()


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Yield one AsyncSession per request; always close it.

    This does NOT commit. Commits belong to the UnitOfWork, so a write that
    happens outside ``async with uow:`` is rolled back on close instead of being
    committed silently. Every repository and the UnitOfWork resolve this same
    session, because FastAPI caches a dependency per request.

    Use as: db: AsyncSession = Depends(get_db).
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_redis() -> AsyncGenerator[Redis]:
    """Yield a Redis client per request.

    Use as: redis: Redis = Depends(get_redis)
    """
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()


async def get_auth_context(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> AuthContext:
    """Authenticate an API key or dashboard JWT and retain its verified identity."""
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
        )
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() != "bearer" or not credential:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header.",
        )

    if looks_like_api_key(credential):
        repository = SQLAlchemyAPIKeyRepository(db)
        cache: ApiKeyAuthCache = RedisApiKeyAuthCache(redis)
        authenticator = ApiKeyAuthenticator(
            cache=cache,
            repository=repository,
            hash_key=hash_api_key,
        )
        try:
            async with SqlAlchemyUnitOfWork(db):
                principal = await authenticator.authenticate(credential)
        except ApiKeyAuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key.",
            ) from exc
        context = AuthContext(
            project_id=principal.project_id,
            method="api_key",
            api_key_id=principal.key_id,
        )
        request.state.auth_context = context
        return context

    try:
        claims = decode_token(credential)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
        ) from exc
    if claims.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        )
    try:
        account_id = UUID(claims["sub"])
        token_id = claims["jti"]
        session_id = claims["sid"]
        token_version = int(claims["ver"])
        token_expiry = int(claims["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        ) from exc
    if not isinstance(token_id, str) or not isinstance(session_id, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        )

    try:
        revoked = await JWTBlocklistStore(redis).is_revoked(jti=token_id)
        revoked = revoked or bool(
            await redis.exists(RedisKeys.auth_session(session_id))
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication state is unavailable.",
        ) from exc
    if revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has been revoked.",
        )

    async with SqlAlchemyUnitOfWork(db):
        account = await SQLAlchemyAuthAccountRepository(db).get_by_id(account_id)
    if (
        account is None
        or not account.is_active
        or not account.is_verified
        or account.auth_version != token_version
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not authorized.",
        )

    context = AuthContext(
        project_id=None,
        method="jwt",
        account_id=account_id,
        token_id=token_id,
        token_expiry=token_expiry,
        session_id=session_id,
    )
    request.state.auth_context = context
    request.state.jwt_claims = claims
    return context


async def get_authenticated_project(
    project_id: UUID,
    request: Request,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectModel:
    """Resolve and authorize a project's API-key or dashboard principal."""
    request.state.auth_context = context
    if context.method == "api_key":
        if context.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key is not authorized for this project.",
            )
        project = await db.get(ProjectModel, project_id)
    else:
        project = await db.scalar(
            select(ProjectModel).where(
                ProjectModel.id == project_id,
                ProjectModel.account_id == context.account_id,
            )
        )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    return project


async def get_current_account(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> AuthAccount:
    """Require a verified dashboard JWT and return its account row."""
    if context.method != "jwt" or context.account_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint requires dashboard authentication.",
        )
    try:
        return await service.get_current_account(context.account_id)
    except AuthenticationOperationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not authorized.",
        ) from exc


# Infrastructure bound to the request session


def get_unit_of_work(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UnitOfWork:
    """Provide the unit of work over the request session."""
    return SqlAlchemyUnitOfWork(db)


def get_notification_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SQLAlchemyNotificationRepository:
    """Provide the SQLAlchemy notification repository bound to the request session."""
    return SQLAlchemyNotificationRepository(db)


def get_recipient_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SQLAlchemyRecipientRepository:
    """Provide the SQLAlchemy recipient repository bound to the request session."""
    return SQLAlchemyRecipientRepository(db)


def get_template_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SQLAlchemyTemplateRepository:
    """Provide the SQLAlchemy template repository bound to the request session."""
    return SQLAlchemyTemplateRepository(db)


def get_intake_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationIntakeRepository:
    """Provide the SQLAlchemy intake repository bound to the request session."""
    return SQLAlchemyNotificationIntakeRepository(db)


def get_outbox(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Outbox:
    """Provide the transactional outbox (writes in the request transaction)."""
    return SQLAlchemyOutbox(db)


def get_topic_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SQLAlchemyNotificationTopicRepository:
    """Provide the SQLAlchemy topic repository bound to the request session."""
    return SQLAlchemyNotificationTopicRepository(db)


def get_rate_limit_policies(
    redis: Annotated[Redis, Depends(get_redis)],
) -> RateLimitPolicies:
    """Provide separately configured public, dashboard, and API policies."""
    return RateLimitPolicies(redis, settings)


def get_auth_email_sender() -> AuthEmailSender:
    """Construct the configured transactional authentication email sender."""
    if settings.email_provider == "resend":
        api_key = settings.resend_api_key
    elif settings.email_provider == "sendgrid":
        api_key = settings.sendgrid_api_key
    else:
        api_key = ""
    return HttpAuthEmailSender(
        provider=settings.email_provider,
        api_key=api_key,
        sender=settings.email_sender,
    )


def get_authentication_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    email_sender: Annotated[AuthEmailSender, Depends(get_auth_email_sender)],
) -> AuthenticationService:
    """Compose the authentication application service."""
    return AuthenticationService(
        unit_of_work=SqlAlchemyUnitOfWork(db),
        accounts=SQLAlchemyAuthAccountRepository(db),
        api_keys=SQLAlchemyAPIKeyRepository(db),
        redis=redis,
        email_sender=email_sender,
        github_provider=HttpGitHubOAuthProvider(),
        settings=settings,
        api_key_cache=RedisApiKeyAuthCache(redis),
    )


def get_api_key_management_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> APIKeyManagementService:
    """Compose the API-key management application service."""
    return APIKeyManagementService(
        unit_of_work=SqlAlchemyUnitOfWork(db),
        projects=SQLAlchemyProjectRepository(db),
        api_keys=SQLAlchemyAPIKeyRepository(db),
        cache=RedisApiKeyAuthCache(redis),
    )


async def _apply_rate_limit(
    *,
    request: Request,
    response: Response,
    limiter: RateLimitPolicies,
    policy: str,
    identity: str,
) -> RateLimitResult:
    """Apply one named policy with an identity-specific Redis namespace."""
    key = RedisKeys.rate_limit(policy, identity)
    dependency = rate_limiter(
        limiter=limiter.limiter,
        rule_name=policy,
        key_extractor=lambda _: key,
    )
    return await dependency(request, response)


async def enforce_auth_rate_limit(
    request: Request,
    response: Response,
    limiter: Annotated[RateLimitPolicies, Depends(get_rate_limit_policies)],
) -> RateLimitResult:
    """Rate-limit unauthenticated auth endpoints by direct client IP."""
    if request.client is None:
        raise RuntimeError("The auth rate limit requires a client address.")
    return await _apply_rate_limit(
        request=request,
        response=response,
        limiter=limiter,
        policy="auth",
        identity=request.client.host,
    )


async def enforce_dashboard_rate_limit(
    request: Request,
    response: Response,
    account: Annotated[AuthAccount, Depends(get_current_account)],
    limiter: Annotated[RateLimitPolicies, Depends(get_rate_limit_policies)],
) -> RateLimitResult:
    """Rate-limit dashboard endpoints by the authenticated account ID."""
    return await _apply_rate_limit(
        request=request,
        response=response,
        limiter=limiter,
        policy="dashboard",
        identity=str(account.id),
    )


async def enforce_authenticated_rate_limit(
    request: Request,
    response: Response,
    project: Annotated[ProjectModel, Depends(get_authenticated_project)],
    limiter: Annotated[RateLimitPolicies, Depends(get_rate_limit_policies)],
) -> RateLimitResult:
    """Rate-limit project routes project tenancy."""
    policy = "api"
    identity = str(project.id)
    return await _apply_rate_limit(
        request=request,
        response=response,
        limiter=limiter,
        policy=policy,
        identity=identity,
    )


# Application services


def get_recipient_resolution_service(
    recipient_repository: Annotated[
        SQLAlchemyRecipientRepository, Depends(get_recipient_repository)
    ],
) -> RecipientResolutionService:
    """Provide registered-recipient lookup and ad-hoc recipient matching."""
    return RecipientResolutionService(recipient_repository=recipient_repository)


def get_notification_intake_service(
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    intake_repository: Annotated[
        NotificationIntakeRepository, Depends(get_intake_repository)
    ],
    outbox: Annotated[Outbox, Depends(get_outbox)],
    recipient_resolution: Annotated[
        RecipientResolutionService, Depends(get_recipient_resolution_service)
    ],
    template_repository: Annotated[
        SQLAlchemyTemplateRepository, Depends(get_template_repository)
    ],
    topic_repository: Annotated[
        SQLAlchemyNotificationTopicRepository, Depends(get_topic_repository)
    ],
) -> NotificationIntakeService:
    """Provide the synchronous accept path (validate, persist intake, enqueue)."""
    return NotificationIntakeService(
        unit_of_work=unit_of_work,
        intake_repository=intake_repository,
        outbox=outbox,
        recipient_resolution=recipient_resolution,
        template_repository=template_repository,
        topic_repository=topic_repository,
    )


def get_notification_query_service(
    notification_repository: Annotated[
        SQLAlchemyNotificationRepository, Depends(get_notification_repository)
    ],
    intake_repository: Annotated[
        NotificationIntakeRepository, Depends(get_intake_repository)
    ],
    recipient_repository: Annotated[
        SQLAlchemyRecipientRepository, Depends(get_recipient_repository)
    ],
) -> NotificationQueryService:
    """Provide the read side of notifications."""
    return NotificationQueryService(
        notification_repository=notification_repository,
        intake_repository=intake_repository,
        recipient_repository=recipient_repository,
    )


def get_notification_cancellation_service(
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    notification_repository: Annotated[
        SQLAlchemyNotificationRepository, Depends(get_notification_repository)
    ],
) -> NotificationCancellationService:
    """Provide the transactional notification-cancellation use case."""
    return NotificationCancellationService(
        unit_of_work=unit_of_work,
        notification_repository=notification_repository,
    )
