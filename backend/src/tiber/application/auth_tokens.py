from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from secrets import randbelow, token_urlsafe
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from redis.exceptions import RedisError

from ..core.config import get_settings
from ..core.redis import RedisKeys, RedisTTL
from ..core.security import create_access_token, create_refresh_token
from .auth import AuthAccount

settings = get_settings()


class AuthStateUnavailableError(RuntimeError):
    """Authentication state could not be read from or written to Redis."""


class AuthTokenConfigurationError(RuntimeError):
    """Authentication token issuance lacks required secret configuration."""


OneTimePurpose = Literal["password-reset"]
EMAIL_VERIFICATION_MAX_ATTEMPTS = 5
EMAIL_VERIFICATION_CODE_LENGTH = 6


@dataclass(frozen=True)
class IssuedTokens:
    """Access and refresh token pair for the API layer to serialize."""

    access_token: str
    refresh_token: str
    expires_in: int


class AuthStateRedis(Protocol):
    """Subset of Redis used by authentication state operations."""

    async def set(self, key: str, value: str, ex: int | None = None) -> Any:
        """Store a string value with an optional expiry."""
        ...

    async def get(self, key: str) -> str | bytes | None:
        """Read a string value."""
        ...

    async def getdel(self, key: str) -> str | bytes | None:
        """Read and atomically remove a string value."""
        ...

    async def exists(self, key: str) -> int:
        """Return the number of keys that exist."""
        ...

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys."""
        ...

    async def eval(
        self,
        script: str,
        number_of_keys: int,
        *keys_and_args: str,
    ) -> Any:
        """Run an atomic Redis Lua script."""
        ...


_CONSUME_ONE_TIME_LUA = """
local account_id = redis.call('GET', KEYS[1])
if not account_id then
    return false
end
local pointer_key = ARGV[2] .. account_id
if redis.call('GET', pointer_key) ~= ARGV[1] then
    return false
end
redis.call('DEL', KEYS[1])
redis.call('DEL', pointer_key)
return account_id
"""

_CONSUME_EMAIL_VERIFICATION_CODE_LUA = """
local code_hash = redis.call('GET', KEYS[1])
if not code_hash then
    return -1
end
local attempts = tonumber(redis.call('GET', KEYS[2]) or '0')
local max_attempts = tonumber(ARGV[2])
if attempts >= max_attempts then
    redis.call('DEL', KEYS[1])
    return -1
end
if code_hash == ARGV[1] then
    redis.call('DEL', KEYS[1], KEYS[2])
    return 1
end
attempts = redis.call('INCR', KEYS[2])
if attempts == 1 then
    local ttl = redis.call('TTL', KEYS[1])
    if ttl > 0 then
        redis.call('EXPIRE', KEYS[2], ttl)
    end
end
if attempts >= max_attempts then
    redis.call('DEL', KEYS[1])
    redis.call('EXPIRE', KEYS[2], ARGV[3])
end
return 0
"""


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _email_verification_code_hash(account_id: UUID, email: str, code: str) -> str:
    if not settings.secret_key:
        raise AuthTokenConfigurationError(
            "Email verification codes require a configured secret key."
        )
    message = f"email-verification:{account_id}:{email}:{code}".encode()
    return hmac.new(settings.secret_key.encode(), message, hashlib.sha256).hexdigest()


async def issue_tokens(
    account: AuthAccount,
    redis: AuthStateRedis,
    *,
    session_id: str | None = None,
) -> IssuedTokens:
    """Issue a JWT access token and a single-use opaque refresh token."""
    current_session = session_id or str(uuid4())
    access_token, _ = create_access_token(
        str(account.id),
        extra={"sid": current_session, "ver": account.auth_version},
    )
    refresh_token = create_refresh_token()
    session_data = json.dumps(
        {
            "account_id": str(account.id),
            "auth_version": account.auth_version,
            "session_id": current_session,
        }
    )
    try:
        await redis.set(
            RedisKeys.refresh_token(_token_hash(refresh_token)),
            session_data,
            ex=settings.refresh_token_expire_days * 24 * 60 * 60,
        )
    except RedisError as exc:
        raise AuthStateUnavailableError(
            "Refresh-token storage is unavailable."
        ) from exc
    return IssuedTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


async def rotate_refresh_token(
    refresh_token: str,
    redis: AuthStateRedis,
) -> tuple[UUID, str, int]:
    """Consume one refresh token and return its account, session, and version."""
    try:
        encoded = await redis.getdel(
            RedisKeys.refresh_token(_token_hash(refresh_token))
        )
    except RedisError as exc:
        raise AuthStateUnavailableError(
            "Refresh-token storage is unavailable."
        ) from exc
    if encoded is None:
        raise ValueError("Invalid or expired refresh token.")

    try:
        data = json.loads(encoded)
        account_id = UUID(data["account_id"])
        session_id = str(data["session_id"])
        auth_version = int(data["auth_version"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("Invalid or expired refresh token.") from exc

    try:
        if await redis.exists(RedisKeys.auth_session(session_id)):
            raise ValueError("Invalid or expired refresh token.")
    except RedisError as exc:
        raise AuthStateUnavailableError("Authentication state is unavailable.") from exc

    return account_id, session_id, auth_version


async def revoke_session(
    session_id: str,
    redis: AuthStateRedis,
) -> None:
    """Block an access-token session until its refresh-token lifetime ends."""
    try:
        await redis.set(
            RedisKeys.auth_session(session_id),
            "1",
            ex=settings.refresh_token_expire_days * 24 * 60 * 60,
        )
    except RedisError as exc:
        raise AuthStateUnavailableError("Authentication state is unavailable.") from exc


async def issue_email_verification_code(
    redis: AuthStateRedis,
    account_id: UUID,
    email: str,
) -> str:
    """Create and store a short-lived, six-digit verification code."""
    code = f"{randbelow(10**EMAIL_VERIFICATION_CODE_LENGTH):0{EMAIL_VERIFICATION_CODE_LENGTH}d}"
    code_hash = _email_verification_code_hash(account_id, email, code)
    try:
        await redis.set(
            RedisKeys.email_verification(account_id),
            code_hash,
            ex=int(RedisTTL.EMAIL_VERIFICATION.total_seconds()),
        )
    except RedisError as exc:
        raise AuthStateUnavailableError("Authentication state is unavailable.") from exc
    return code


async def consume_email_verification_code(
    redis: AuthStateRedis,
    account_id: UUID,
    email: str,
    code: str,
) -> bool:
    """Atomically consume the current code while limiting incorrect guesses."""
    code_hash = _email_verification_code_hash(account_id, email, code)
    try:
        result = await redis.eval(
            _CONSUME_EMAIL_VERIFICATION_CODE_LUA,
            2,
            RedisKeys.email_verification(account_id),
            RedisKeys.email_verification_attempts(account_id),
            code_hash,
            str(EMAIL_VERIFICATION_MAX_ATTEMPTS),
            str(int(RedisTTL.EMAIL_VERIFICATION.total_seconds())),
        )
    except RedisError as exc:
        raise AuthStateUnavailableError("Authentication state is unavailable.") from exc
    return result == 1 or result == b"1"


async def issue_one_time_token(
    redis: AuthStateRedis,
    account_id: UUID,
    purpose: OneTimePurpose,
) -> str:
    """Create and store a hash-only password-reset link token."""
    token = token_urlsafe(32)
    token_hash = _token_hash(token)
    pointer_key, token_key, ttl = _one_time_keys(account_id, token_hash, purpose)
    try:
        previous_hash = await redis.get(pointer_key)
        if previous_hash is not None:
            if isinstance(previous_hash, bytes):
                previous_hash = previous_hash.decode()
            await redis.delete(_one_time_token_key(str(previous_hash), purpose))
        await redis.set(pointer_key, token_hash, ex=ttl)
        await redis.set(token_key, str(account_id), ex=ttl)
    except RedisError as exc:
        raise AuthStateUnavailableError("Authentication state is unavailable.") from exc
    return token


async def consume_one_time_token(
    redis: AuthStateRedis,
    token: str,
    purpose: OneTimePurpose,
) -> UUID | None:
    """Atomically consume the current one-time token for an account."""
    token_hash = _token_hash(token)
    token_key = _one_time_token_key(token_hash, purpose)
    pointer_prefix = _one_time_pointer_prefix(purpose)
    try:
        account_id = await redis.eval(
            _CONSUME_ONE_TIME_LUA,
            1,
            token_key,
            token_hash,
            pointer_prefix,
        )
    except RedisError as exc:
        raise AuthStateUnavailableError("Authentication state is unavailable.") from exc
    if isinstance(account_id, bytes):
        account_id = account_id.decode()
    return UUID(account_id) if account_id else None


def _one_time_keys(
    account_id: UUID,
    token_hash: str,
    purpose: OneTimePurpose,
) -> tuple[str, str, int]:
    del purpose
    return (
        RedisKeys.password_reset(account_id),
        RedisKeys.password_reset_token(token_hash),
        int(RedisTTL.PASSWORD_RESET.total_seconds()),
    )


def _one_time_token_key(token_hash: str, purpose: OneTimePurpose) -> str:
    del purpose
    return RedisKeys.password_reset_token(token_hash)


def _one_time_pointer_prefix(purpose: OneTimePurpose) -> str:
    del purpose
    return RedisKeys.password_reset_account_prefix()
