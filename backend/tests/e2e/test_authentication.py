from __future__ import annotations

import re
from uuid import uuid4

import pytest

pytestmark = pytest.mark.e2e


class MemoryRedis:
    """Small async Redis fake for token and API-key cache journeys."""

    def __init__(self) -> None:
        """Create an empty in-memory key/value store."""
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, ex=None) -> bool:
        """Store a string value and ignore expiration in this short-lived test."""
        self.values[key] = str(value)
        return True

    async def get(self, key: str) -> str | None:
        """Return a stored string or None."""
        return self.values.get(key)

    async def getdel(self, key: str) -> str | None:
        """Return and remove one stored value."""
        return self.values.pop(key, None)

    async def exists(self, key: str) -> int:
        """Return Redis-style existence count."""
        return int(key in self.values)

    async def delete(self, key: str) -> int:
        """Delete a key and return the number of removed entries."""
        return int(self.values.pop(key, None) is not None)

    async def eval(self, script: str, number_of_keys: int, token_key: str, *args):
        """Apply the one-time token check-and-delete script."""
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


class RecordingEmailSender:
    """Capture outgoing email bodies without exposing tokens through logs."""

    def __init__(self) -> None:
        """Initialize an empty message capture."""
        self.messages: list[tuple[str, str, str]] = []

    async def send(self, recipient: str, subject: str, body: str) -> None:
        """Record one message for the test to inspect."""
        self.messages.append((recipient, subject, body))


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_register_verify_and_access_dashboard(
    client,
    app,
    monkeypatch,
) -> None:
    """Registration requires verification before a dashboard JWT is issued."""
    from tiber.api import dependencies as deps
    from tiber.core import security

    redis = MemoryRedis()
    email_sender = RecordingEmailSender()
    app.dependency_overrides[deps.get_redis] = lambda: redis
    app.dependency_overrides[deps.get_auth_email_sender] = lambda: email_sender
    monkeypatch.setattr(security.settings, "secret_key", "test-signing-key")

    registered = await client.post(
        "/v1/auth/register",
        json={"email": "new-account@example.com", "password": "correct horse battery"},
    )

    assert registered.status_code == 202
    assert len(email_sender.messages) == 1
    code = re.search(r"(?<!\d)\d{6}(?!\d)", email_sender.messages[0][2])
    assert code is not None

    verified = await client.post(
        "/v1/auth/email/verify",
        json={"email": "new-account@example.com", "otp": code.group(0)},
    )

    assert verified.status_code == 200
    token_response = verified.json()
    assert token_response["token_type"] == "bearer"  # noqa: S105
    assert token_response["expires_in"] > 0

    profile = await client.get(
        "/v1/auth/me",
        headers=_bearer(token_response["access_token"]),
    )

    assert profile.status_code == 200
    assert profile.json()["email"] == "new-account@example.com"
    assert profile.json()["is_verified"] is True

    logged_in = await client.post(
        "/v1/auth/login",
        json={"email": "new-account@example.com", "password": "correct horse battery"},
    )
    assert logged_in.status_code == 200

    original_refresh = logged_in.json()["refresh_token"]
    rotated = await client.post(
        "/v1/auth/refresh",
        json={"refresh_token": original_refresh},
    )
    assert rotated.status_code == 200
    replayed = await client.post(
        "/v1/auth/refresh",
        json={"refresh_token": original_refresh},
    )
    assert replayed.status_code == 401

    logged_out = await client.post(
        "/v1/auth/logout",
        headers=_bearer(rotated.json()["access_token"]),
    )
    assert logged_out.status_code == 204
    revoked_access = await client.get(
        "/v1/auth/me",
        headers=_bearer(rotated.json()["access_token"]),
    )
    assert revoked_access.status_code == 401
    revoked_refresh = await client.post(
        "/v1/auth/refresh",
        json={"refresh_token": rotated.json()["refresh_token"]},
    )
    assert revoked_refresh.status_code == 401

    reset_requested = await client.post(
        "/v1/auth/password/reset-request",
        json={"email": "new-account@example.com"},
    )
    assert reset_requested.status_code == 202
    reset_link = re.search(
        r"/auth/reset-password\?token=([A-Za-z0-9_-]+)",
        email_sender.messages[-1][2],
    )
    assert reset_link is not None

    reset = await client.post(
        "/v1/auth/password/reset",
        json={
            "token": reset_link.group(1),
            "password": "another correct horse battery",
        },
    )
    assert reset.status_code == 204
    assert (
        await client.post(
            "/v1/auth/login",
            json={
                "email": "new-account@example.com",
                "password": "correct horse battery",
            },
        )
    ).status_code == 401
    assert (
        await client.post(
            "/v1/auth/login",
            json={
                "email": "new-account@example.com",
                "password": "another correct horse battery",
            },
        )
    ).status_code == 200


async def test_api_key_is_project_scoped_and_revoke_takes_effect(
    client,
    app,
    session,
    monkeypatch,
) -> None:
    """A dashboard creates a key, the key accesses only its project, and revocation works."""
    from tiber.api import dependencies as deps
    from tiber.api.auth_tokens import issue_tokens
    from tiber.core import security
    from tiber.infrastructure.models import AccountModel, ProjectModel

    app.dependency_overrides.pop(deps.get_authenticated_project, None)
    redis = MemoryRedis()
    app.dependency_overrides[deps.get_redis] = lambda: redis
    monkeypatch.setattr(security.settings, "secret_key", "test-signing-key")

    account = AccountModel(
        email=f"auth-{uuid4().hex}@example.com",
        is_verified=True,
    )
    session.add(account)
    await session.flush()
    project = ProjectModel(
        account_id=account.id,
        name="Auth e2e",
        slug=f"auth-{uuid4().hex[:12]}",
    )
    session.add(project)
    await session.commit()
    project_id = project.id
    await session.refresh(account)

    tokens = await issue_tokens(account, redis)
    dashboard_headers = _bearer(tokens.access_token)
    created = await client.post(
        f"/v1/projects/{project_id}/api-keys",
        headers=dashboard_headers,
        json={"name": "integration"},
    )

    assert created.status_code == 201
    key_response = created.json()
    raw_key = key_response["key"]
    assert raw_key.startswith("tb_")
    assert "key_hash" not in key_response

    notification_list = await client.get(
        f"/projects/{project_id}/notifications",
        headers=_bearer(raw_key),
    )
    assert notification_list.status_code == 200

    outside_project = await client.get(
        f"/projects/{uuid4()}/notifications",
        headers=_bearer(raw_key),
    )
    assert outside_project.status_code == 403

    revoked = await client.delete(
        f"/v1/projects/{project_id}/api-keys/{key_response['id']}",
        headers=dashboard_headers,
    )
    assert revoked.status_code == 204

    rejected = await client.get(
        f"/projects/{project_id}/notifications",
        headers=_bearer(raw_key),
    )
    assert rejected.status_code == 401
