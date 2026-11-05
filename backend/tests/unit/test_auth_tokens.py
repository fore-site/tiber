from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from tiber.api.auth_tokens import (
    consume_one_time_token,
    issue_one_time_token,
    issue_tokens,
    rotate_refresh_token,
)
from tiber.application.auth_tokens import (
    EMAIL_VERIFICATION_MAX_ATTEMPTS,
    consume_email_verification_code,
    issue_email_verification_code,
)
from tiber.application.auth_tokens import (
    settings as auth_token_settings,
)
from tiber.core import security
from tiber.core.redis import RedisKeys
from tiber.infrastructure.models import AccountModel


class MemoryRedis:
    """Minimal Redis fake for refresh and one-time auth token tests."""

    def __init__(self) -> None:
        """Create an empty key/value store."""
        self.values: dict[str, str] = {}
        self.expiries: dict[str, Any] = {}

    async def set(self, key: str, value: str, ex=None) -> bool:
        """Store a string value."""
        self.values[key] = str(value)
        self.expiries[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        """Read a string value."""
        return self.values.get(key)

    async def getdel(self, key: str) -> str | None:
        """Read and atomically remove a string value."""
        return self.values.pop(key, None)

    async def exists(self, key: str) -> int:
        """Return a Redis-style existence count."""
        return int(key in self.values)

    async def delete(self, *keys: str) -> int:
        """Delete values if present."""
        return sum(self.values.pop(key, None) is not None for key in keys)

    async def eval(
        self,
        script: str,
        number_of_keys: int,
        token_key: str,
        *args: str,
    ):
        """Apply the token-consumption Lua contract."""
        del script
        if number_of_keys == 2:
            attempts_key, code_hash, max_attempts, _attempt_ttl = args
            active_hash = self.values.get(token_key)
            if active_hash is None:
                return -1
            attempts = int(self.values.get(attempts_key, "0"))
            if attempts >= int(max_attempts):
                self.values.pop(token_key, None)
                return -1
            if active_hash == code_hash:
                self.values.pop(token_key, None)
                self.values.pop(attempts_key, None)
                return 1
            attempts += 1
            if attempts >= int(max_attempts):
                self.values.pop(token_key, None)
                self.values[attempts_key] = str(attempts)
            else:
                self.values[attempts_key] = str(attempts)
            return 0
        token_hash, pointer_prefix = args
        account_id = self.values.get(token_key)
        if account_id is None:
            return None
        pointer_key = f"{pointer_prefix}{account_id}"
        if self.values.get(pointer_key) != token_hash:
            return None
        del self.values[token_key]
        del self.values[pointer_key]
        return account_id


@pytest.fixture
def account() -> AccountModel:
    """Build an authenticated account without requiring a database."""
    return AccountModel(
        id=uuid4(),
        email="verified@example.com",
        is_verified=True,
        auth_version=4,
    )


async def test_refresh_tokens_are_opaque_single_use_and_rotated(
    account: AccountModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rotation consumes the old secret and carries the same session forward."""
    monkeypatch.setattr(security.settings, "secret_key", "test-signing-key")
    redis = MemoryRedis()

    issued = await issue_tokens(account, redis)
    assert issued.refresh_token not in redis.values
    assert len(redis.values) == 1

    account_id, session_id, auth_version = await rotate_refresh_token(
        issued.refresh_token,
        redis,
    )

    assert account_id == account.id
    assert auth_version == account.auth_version
    with pytest.raises(ValueError, match="Invalid or expired"):
        await rotate_refresh_token(issued.refresh_token, redis)

    rotated = await issue_tokens(account, redis, session_id=session_id)
    assert rotated.refresh_token != issued.refresh_token
    assert len(redis.values) == 1


async def test_password_reset_tokens_are_invalidated_on_resend_and_consumed_once() -> (
    None
):
    """Only the current password-reset link token can be consumed once."""
    account_id = uuid4()
    redis = MemoryRedis()

    previous = await issue_one_time_token(redis, account_id, "password-reset")
    current = await issue_one_time_token(redis, account_id, "password-reset")

    assert (
        await consume_one_time_token(
            redis,
            previous,
            "password-reset",
        )
        is None
    )
    assert (
        await consume_one_time_token(
            redis,
            current,
            "password-reset",
        )
        == account_id
    )
    assert (
        await consume_one_time_token(
            redis,
            current,
            "password-reset",
        )
        is None
    )


async def test_email_verification_code_is_six_digits_single_use_and_short_lived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verification codes are email-bound and expire after ten minutes."""
    monkeypatch.setattr(auth_token_settings, "secret_key", "test-signing-key")
    account_id = uuid4()
    email = "verified@example.com"
    redis = MemoryRedis()

    code = await issue_email_verification_code(redis, account_id, email)
    assert len(code) == 6 and code.isdigit()
    assert redis.expiries[RedisKeys.email_verification(account_id)] == 600

    assert not await consume_email_verification_code(
        redis,
        account_id,
        email,
        "000000" if code != "000000" else "000001",
    )
    assert not await consume_email_verification_code(
        redis,
        account_id,
        "different@example.com",
        code,
    )
    assert await consume_email_verification_code(
        redis,
        account_id,
        email,
        code,
    )
    assert not await consume_email_verification_code(
        redis,
        account_id,
        email,
        code,
    )


async def test_email_verification_code_locks_after_maximum_wrong_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid code cannot be guessed after five incorrect submissions."""
    monkeypatch.setattr(auth_token_settings, "secret_key", "test-signing-key")
    account_id = uuid4()
    email = "verified@example.com"
    redis = MemoryRedis()
    code = await issue_email_verification_code(redis, account_id, email)
    wrong_code = "000000" if code != "000000" else "000001"

    for _ in range(EMAIL_VERIFICATION_MAX_ATTEMPTS):
        assert not await consume_email_verification_code(
            redis,
            account_id,
            email,
            wrong_code,
        )

    assert not await consume_email_verification_code(
        redis,
        account_id,
        email,
        code,
    )
    resent_code = await issue_email_verification_code(redis, account_id, email)
    assert not await consume_email_verification_code(
        redis,
        account_id,
        email,
        resent_code,
    )


def test_redis_rate_limit_namespaces_are_isolated_by_policy_and_identity() -> None:
    """Auth, dashboard, and project API policies use separate counters."""
    account_id = uuid4()
    project_id = uuid4()

    auth_key = RedisKeys.rate_limit("auth", "192.0.2.1")
    dashboard_key = RedisKeys.rate_limit("dashboard", str(account_id))
    api_key = RedisKeys.rate_limit("api", str(project_id))

    assert len({auth_key, dashboard_key, api_key}) == 3
    assert api_key == RedisKeys.rate_limit(
        "api",
        str(project_id),
    )
