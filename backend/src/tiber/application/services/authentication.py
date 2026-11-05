"""Use cases for account authentication and lifecycle management."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from secrets import token_urlsafe
from typing import Literal
from urllib.parse import urlencode
from uuid import UUID, uuid4

from redis.exceptions import RedisError

from ...core.config import Settings
from ...core.redis import RedisKeys, RedisTTL
from ...core.security import hash_password, verify_password
from ...domain.repositories import APIKeyRepository
from ..auth import AuthAccount, AuthContext
from ..auth_tokens import (
    AuthStateRedis,
    AuthStateUnavailableError,
    AuthTokenConfigurationError,
    IssuedTokens,
    OneTimePurpose,
    consume_email_verification_code,
    consume_one_time_token,
    issue_email_verification_code,
    issue_one_time_token,
    issue_tokens,
    revoke_session,
    rotate_refresh_token,
)
from ..ports.api_key_auth_cache import ApiKeyAuthCache
from ..ports.auth_account_repository import (
    AccountIdentityConflictError,
    AuthAccountRepository,
)
from ..ports.auth_email_sender import AuthEmailDeliveryError, AuthEmailSender
from ..ports.github_oauth import GitHubOAuthError, GitHubOAuthProvider
from ..ports.unit_of_work import UnitOfWork


class AuthenticationOperationError(RuntimeError):
    """A rejected authentication or account-lifecycle operation."""

    def __init__(self, code: str) -> None:
        """Store the stable application error code."""
        super().__init__(code)
        self.code = code


class AuthenticationService:
    """Coordinate account repositories, transactions, token state, and providers."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        accounts: AuthAccountRepository,
        api_keys: APIKeyRepository,
        redis: AuthStateRedis,
        email_sender: AuthEmailSender,
        github_provider: GitHubOAuthProvider,
        settings: Settings,
        api_key_cache: ApiKeyAuthCache,
    ) -> None:
        """Bind application ports and infrastructure adapters."""
        self._uow = unit_of_work
        self._accounts = accounts
        self._api_keys = api_keys
        self._redis = redis
        self._email_sender = email_sender
        self._github = github_provider
        self._settings = settings
        self._api_key_cache = api_key_cache

    async def get_current_account(self, account_id: UUID) -> AuthAccount:
        """Load an active, verified dashboard account."""
        async with self._uow:
            account = await self._accounts.get_by_id(account_id)
        if account is None or not account.is_active or not account.is_verified:
            raise AuthenticationOperationError("account_not_authorized")
        return account

    async def register(self, email: str, password: str) -> None:
        """Create an unverified account and deliver its verification code."""
        account = AuthAccount(
            id=uuid4(),
            email=email,
            role="user",
            is_verified=False,
            is_active=True,
            auth_version=0,
            pending_email=None,
            password_hash=await asyncio.to_thread(hash_password, password),
            github_id=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        try:
            async with self._uow:
                await self._accounts.add(account)
        except AccountIdentityConflictError as exc:
            raise AuthenticationOperationError("account_exists") from exc
        await self._send_one_time_email(account, "email-verification")

    async def login(self, email: str, password: str) -> IssuedTokens:
        """Verify account credentials and issue a token pair."""
        async with self._uow:
            account = await self._accounts.get_by_email(email)
        if account is None or not account.is_active or account.password_hash is None:
            await asyncio.to_thread(hash_password, password)
            raise AuthenticationOperationError("invalid_credentials")
        if not await asyncio.to_thread(
            verify_password, password, account.password_hash
        ):
            raise AuthenticationOperationError("invalid_credentials")
        if not account.is_verified:
            raise AuthenticationOperationError("email_not_verified")
        return await self._issue_tokens(account)

    async def refresh(self, refresh_token: str) -> IssuedTokens:
        """Consume and rotate a refresh token after checking account state."""
        try:
            account_id, session_id, auth_version = await rotate_refresh_token(
                refresh_token,
                self._redis,
            )
        except ValueError as exc:
            raise AuthenticationOperationError("invalid_refresh_token") from exc
        except AuthStateUnavailableError as exc:
            raise AuthenticationOperationError("auth_state_unavailable") from exc

        async with self._uow:
            account = await self._accounts.get_by_id(account_id)
        if (
            account is None
            or not account.is_active
            or not account.is_verified
            or account.auth_version != auth_version
        ):
            raise AuthenticationOperationError("invalid_refresh_token")
        return await self._issue_tokens(account, session_id=session_id)

    async def logout(self, context: AuthContext) -> None:
        """Revoke the current access-token JTI and its refresh-token session."""
        if context.token_id is None or context.token_expiry is None:
            raise AuthenticationOperationError("invalid_access_token")
        try:
            expiry = datetime.fromtimestamp(context.token_expiry, tz=UTC)
            ttl = (expiry - datetime.now(UTC)) + RedisTTL.CLOCK_SKEW
            if ttl.total_seconds() > 0:
                await self._redis.set(
                    RedisKeys.jwt_blocklist(context.token_id),
                    "1",
                    ex=int(ttl.total_seconds()),
                )
            if context.session_id is not None:
                await revoke_session(context.session_id, self._redis)
        except (RedisError, AuthStateUnavailableError) as exc:
            raise AuthenticationOperationError("auth_state_unavailable") from exc

    async def update_email(self, account_id: UUID, email: str) -> AuthAccount:
        """Record a pending email change and send its verification code."""
        async with self._uow:
            account = await self._required_account(account_id)
            if email == account.email:
                return account
            if await self._accounts.get_by_email(email) is not None:
                raise AuthenticationOperationError("account_exists")
            account.pending_email = email
            await self._accounts.save(account)
        await self._send_one_time_email(account, "email-verification", email)
        return account

    async def deactivate(self, account_id: UUID) -> None:
        """Deactivate an account, revoke owned keys, then invalidate their cache."""
        try:
            async with self._uow:
                account = await self._required_account(account_id)
                keys = await self._api_keys.list_by_account(account_id)
                for key in keys:
                    await self._api_keys.save(key.revoke())
                account.is_active = False
                account.is_verified = False
                account.pending_email = None
                account.password_hash = None
                account.github_id = None
                account.email = f"deleted-{account.id}@deleted.invalid"
                account.auth_version += 1
                await self._accounts.save(account)
        except AccountIdentityConflictError as exc:
            raise AuthenticationOperationError("account_identity_conflict") from exc

        try:
            for key in keys:
                await self._api_key_cache.invalidate(key.key_hash)
        except RedisError as exc:
            raise AuthenticationOperationError("api_key_state_unavailable") from exc

    async def verify_email(self, email: str, code: str) -> IssuedTokens:
        """Consume a verification code and activate registration or email change."""
        try:
            async with self._uow:
                account = await self._accounts.get_by_email_or_pending_email(email)
                if account is None or not account.is_active:
                    raise AuthenticationOperationError("invalid_verification_code")
                if not await consume_email_verification_code(
                    self._redis,
                    account.id,
                    email,
                    code,
                ):
                    raise AuthenticationOperationError("invalid_verification_code")
                if account.pending_email is not None:
                    account.email = account.pending_email
                    account.pending_email = None
                account.is_verified = True
                account.auth_version += 1
                await self._accounts.save(account)
        except AccountIdentityConflictError as exc:
            raise AuthenticationOperationError("email_identity_conflict") from exc
        except AuthStateUnavailableError as exc:
            raise AuthenticationOperationError("auth_state_unavailable") from exc
        except AuthTokenConfigurationError as exc:
            raise AuthenticationOperationError("otp_not_configured") from exc
        return await self._issue_tokens(account)

    async def resend_verification(self, email: str) -> None:
        """Send a verification code to an unverified or pending email address."""
        async with self._uow:
            account = await self._accounts.get_by_email_or_pending_email(email)
        if (
            account is not None
            and account.is_active
            and (not account.is_verified or account.pending_email == email)
        ):
            await self._send_one_time_email(
                account,
                "email-verification",
                email,
            )

    async def github_authorization_url(self) -> str:
        """Create OAuth state and return GitHub's authorization URL."""
        self._require_github_configuration()
        state = token_urlsafe(32)
        try:
            await self._redis.set(
                RedisKeys.github_oauth_state(self._token_digest(state)),
                "1",
                ex=int(RedisTTL.GITHUB_OAUTH_STATE.total_seconds()),
            )
        except RedisError as exc:
            raise AuthenticationOperationError("auth_state_unavailable") from exc
        query = urlencode(
            {
                "client_id": self._settings.github_oauth_client_id,
                "redirect_uri": self._settings.github_oauth_redirect_uri,
                "scope": "read:user user:email",
                "state": state,
            }
        )
        return f"https://github.com/login/oauth/authorize?{query}"

    async def github_callback(self, code: str, state: str) -> IssuedTokens:
        """Validate OAuth state, resolve/link the account, and issue tokens."""
        self._require_github_configuration()
        try:
            valid_state = await self._redis.getdel(
                RedisKeys.github_oauth_state(self._token_digest(state))
            )
        except RedisError as exc:
            raise AuthenticationOperationError("auth_state_unavailable") from exc
        if valid_state is None:
            raise AuthenticationOperationError("invalid_oauth_state")

        try:
            identity = await self._github.authenticate(
                code=code,
                client_id=self._settings.github_oauth_client_id,
                client_secret=self._settings.github_oauth_client_secret,
                redirect_uri=self._settings.github_oauth_redirect_uri,
            )
        except GitHubOAuthError as exc:
            raise AuthenticationOperationError(str(exc)) from exc

        try:
            async with self._uow:
                account = await self._accounts.get_by_github_id(identity.github_id)
                if account is None:
                    account = await self._accounts.get_by_email(identity.email)
                    if account is not None and account.github_id not in {
                        None,
                        identity.github_id,
                    }:
                        raise AuthenticationOperationError("github_identity_conflict")
                    if account is None:
                        now = datetime.now(UTC)
                        account = AuthAccount(
                            id=uuid4(),
                            email=identity.email,
                            role="user",
                            is_verified=True,
                            is_active=True,
                            auth_version=0,
                            pending_email=None,
                            password_hash=None,
                            github_id=identity.github_id,
                            created_at=now,
                            updated_at=now,
                        )
                        await self._accounts.add(account)
                    else:
                        account.github_id = identity.github_id
                        account.is_verified = True
                        await self._accounts.save(account)
                if not account.is_active:
                    raise AuthenticationOperationError("account_not_authorized")
        except AccountIdentityConflictError as exc:
            raise AuthenticationOperationError("github_identity_conflict") from exc
        return await self._issue_tokens(account)

    async def change_password(
        self,
        account_id: UUID,
        current_password: str,
        new_password: str,
        context: AuthContext,
    ) -> None:
        """Change the account password, invalidate old tokens, and log out current session."""
        async with self._uow:
            account = await self._required_account(account_id)
            if account.password_hash is None:
                raise AuthenticationOperationError("no_password_set")
            valid = await asyncio.to_thread(
                verify_password,
                current_password,
                account.password_hash,
            )
            if not valid:
                raise AuthenticationOperationError("invalid_current_password")
            account.password_hash = await asyncio.to_thread(hash_password, new_password)
            account.auth_version += 1
            await self._accounts.save(account)
        await self.logout(context)

    async def request_password_reset(self, email: str) -> None:
        """Send a password reset link without revealing whether the account exists."""
        async with self._uow:
            account = await self._accounts.get_by_email(email)
        if account is not None and account.is_active:
            await self._send_one_time_email(account, "password-reset")

    async def reset_password(self, token: str, password: str) -> None:
        """Consume a password-reset token and replace the password credential."""
        account_id = await self._consume_one_time_token(
            token,
            "password-reset",
            error_code="invalid_password_reset_token",
        )
        async with self._uow:
            account = await self._accounts.get_by_id(account_id)
            if account is None or not account.is_active:
                raise AuthenticationOperationError("invalid_password_reset_token")
            account.password_hash = await asyncio.to_thread(hash_password, password)
            account.auth_version += 1
            await self._accounts.save(account)

    async def _required_account(self, account_id: UUID) -> AuthAccount:
        account = await self._accounts.get_by_id(account_id)
        if account is None or not account.is_active:
            raise AuthenticationOperationError("account_not_authorized")
        return account

    async def _issue_tokens(
        self,
        account: AuthAccount,
        *,
        session_id: str | None = None,
    ) -> IssuedTokens:
        if not self._settings.secret_key:
            raise AuthenticationOperationError("jwt_not_configured")
        try:
            return await issue_tokens(account, self._redis, session_id=session_id)
        except AuthStateUnavailableError as exc:
            raise AuthenticationOperationError("auth_state_unavailable") from exc

    async def _send_one_time_email(
        self,
        account: AuthAccount,
        purpose: Literal["email-verification", "password-reset"],
        recipient: str | None = None,
    ) -> None:
        try:
            if purpose == "email-verification":
                destination = recipient or account.pending_email or account.email
                token = await issue_email_verification_code(
                    self._redis,
                    account.id,
                    destination,
                )
            else:
                token = await issue_one_time_token(self._redis, account.id, purpose)
        except AuthTokenConfigurationError as exc:
            raise AuthenticationOperationError("otp_not_configured") from exc
        except AuthStateUnavailableError as exc:
            raise AuthenticationOperationError("auth_state_unavailable") from exc
        if purpose == "email-verification":
            subject = "Verify your Tiber account"
            body = (
                f"Your Tiber email verification code is: {token}\n\n"
                "This code expires in 10 minutes. If you did not request this, "
                "you can ignore this message."
            )
        else:
            subject = "Reset your Tiber password"
            target = f"{self._settings.dashboard_url.rstrip('/')}/auth/reset-password"
            body = (
                f"Use this link to reset your Tiber password:\n\n"
                f"{target}?token={token}\n\n"
                "If you did not request this, you can ignore this message."
            )
        try:
            await self._email_sender.send(recipient or account.email, subject, body)
        except AuthEmailDeliveryError as exc:
            raise AuthenticationOperationError("email_delivery_failed") from exc

    async def _consume_one_time_token(
        self,
        token: str,
        purpose: OneTimePurpose,
        *,
        error_code: str,
    ) -> UUID:
        try:
            account_id = await consume_one_time_token(
                self._redis,
                token,
                purpose,
            )
        except AuthStateUnavailableError as exc:
            raise AuthenticationOperationError("auth_state_unavailable") from exc
        if account_id is None:
            raise AuthenticationOperationError(error_code)
        return account_id

    def _require_github_configuration(self) -> None:
        if (
            not self._settings.github_oauth_client_id
            or not self._settings.github_oauth_client_secret
        ):
            raise AuthenticationOperationError("github_not_configured")

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
