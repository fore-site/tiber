from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tiber.domain.entities import APIKey
from tiber.domain.exceptions import InvalidEntityAttributeError


def make_api_key(**changes) -> APIKey:
    """Build an API key with valid defaults and selected field overrides."""
    values = {
        "project_id": uuid4(),
        "name": "Production",
        "key_hash": "hash",
        "key_prefix": "tb_prefix",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values.update(changes)
    return APIKey(**values)


def test_revoke_returns_a_new_inactive_entity_without_mutating_original() -> None:
    """Revocation returns a new immutable entity and preserves the original."""
    key = make_api_key()
    revoked_at = datetime(2026, 1, 2, tzinfo=UTC)

    revoked = key.revoke(at=revoked_at)

    assert key.revoked_at is None
    assert key.is_active(revoked_at)
    assert revoked is not key
    assert revoked.revoked_at == revoked_at
    assert not revoked.is_active(revoked_at)


def test_revoke_is_idempotent() -> None:
    """Revoking an already-revoked key returns the existing entity."""
    revoked = make_api_key().revoke(at=datetime(2026, 1, 2, tzinfo=UTC))

    result = revoked.revoke(at=datetime(2026, 1, 3, tzinfo=UTC))

    assert result is revoked
    assert result.revoked_at == datetime(2026, 1, 2, tzinfo=UTC)


def test_create_accepts_an_expiration_and_expiry_is_inclusive() -> None:
    """Expiration is accepted and becomes effective at the exact boundary."""
    expires_at = datetime(2026, 1, 2, tzinfo=UTC)
    key = make_api_key(expires_at=expires_at)

    assert key.is_active(datetime(2026, 1, 1, 23, 59, tzinfo=UTC))
    assert key.is_expired(expires_at)
    assert not key.is_active(expires_at)


@pytest.mark.parametrize("field_name", ["created_at", "revoked_at", "expires_at"])
def test_timestamps_must_be_timezone_aware(field_name: str) -> None:
    """All persisted API-key timestamps must carry timezone information."""
    values = {field_name: datetime(2026, 1, 1)}

    with pytest.raises(InvalidEntityAttributeError, match="timezone-aware"):
        make_api_key(**values)


def test_revoke_rejects_a_naive_timestamp() -> None:
    """The revoke operation rejects a naive timestamp."""
    with pytest.raises(InvalidEntityAttributeError, match="timezone-aware"):
        make_api_key().revoke(at=datetime(2026, 1, 2))
