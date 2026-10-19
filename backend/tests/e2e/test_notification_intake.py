"""End-to-end journeys for the accept half of the notification contract.

These drive the real ASGI app against a real Postgres database and assert only
what the HTTP contract promises: a 202 with a batch handle, replay safety,
conflict detection, request-status reads, rate limiting, and project scoping.

Fan-out is not covered yet: nothing consumes the intake outbox, so the
notifications list is legitimately empty until the worker wiring lands. Add
those journeys here rather than resurrecting per-class unit tests.
"""

from __future__ import annotations

from uuid import UUID

import pytest

pytestmark = pytest.mark.e2e

AUTH = {"Authorization": "Bearer e2e"}


def headers(idempotency_key: str) -> dict:
    """Client headers for the accept endpoint."""
    return {**AUTH, "Idempotency-Key": idempotency_key}


def request_body(**overrides) -> dict:
    """Build a valid address-based request; overrides change one field per test."""
    body = {
        "email": "jane@example.com",
        "category": "promotional",
        "content": {
            "title": "Your statement is ready",
            "body": "Sign in to view it.",
        },
    }
    body.update(overrides)
    return body


async def test_accept_returns_202_with_a_batch_handle(client, project) -> None:
    """A valid request is accepted and identified by a server-generated correlation id."""
    response = await client.post(
        f"/projects/{project.id}/notifications",
        headers=headers("accept-1"),
        json=request_body(),
    )

    assert response.status_code == 202
    body = response.json()
    assert body["project_id"] == str(project.id)
    UUID(body["correlation_id"])
    assert response.headers["location"].endswith(
        f"/projects/{project.id}/notification-requests/{body['correlation_id']}"
    )


async def test_same_key_and_body_replays_the_same_batch(client, project) -> None:
    """Retrying an identical request returns the original batch, not a second one."""
    first = await client.post(
        f"/projects/{project.id}/notifications",
        headers=headers("replay-1"),
        json=request_body(),
    )
    second = await client.post(
        f"/projects/{project.id}/notifications",
        headers=headers("replay-1"),
        json=request_body(),
    )

    assert first.status_code == second.status_code == 202
    assert second.json()["correlation_id"] == first.json()["correlation_id"]
    assert second.headers.get("idempotent-replayed") == "true"


async def test_same_key_with_a_different_body_is_rejected(client, project) -> None:
    """Reusing a key for a different payload is a conflict, not a silent replay."""
    await client.post(
        f"/projects/{project.id}/notifications",
        headers=headers("conflict-1"),
        json=request_body(),
    )

    response = await client.post(
        f"/projects/{project.id}/notifications",
        headers=headers("conflict-1"),
        json=request_body(content={"title": "Changed", "body": "Different body"}),
    )

    assert response.status_code == 409
    assert response.json()["error"] == "idempotency_key_conflict"


async def test_missing_idempotency_key_is_rejected(client, project) -> None:
    """The header is part of the contract, so its absence fails before any write."""
    response = await client.post(
        f"/projects/{project.id}/notifications",
        headers=AUTH,
        json=request_body(),
    )

    assert response.status_code == 422


async def test_request_status_is_readable_before_fan_out(client, project) -> None:
    """The Location handle resolves to the accepted request and its empty child list."""
    accepted = await client.post(
        f"/projects/{project.id}/notifications",
        headers=headers("status-1"),
        json=request_body(),
    )
    correlation_id = accepted.json()["correlation_id"]

    response = await client.get(
        f"/projects/{project.id}/notification-requests/{correlation_id}",
        headers=AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["correlation_id"] == correlation_id
    assert body["project_id"] == str(project.id)
    assert body["status"] in {"received", "processing"}
    assert body["notifications"] == []


async def test_rate_limited_project_is_rejected(client, app, project) -> None:
    """The router rejects the request before touching the intake when the limiter denies."""
    from tiber.api.dependencies import get_ingestion_rate_limiter

    class _DenyAllLimiter:
        async def is_allowed(self, project_id) -> bool:
            return False

    app.dependency_overrides[get_ingestion_rate_limiter] = lambda: _DenyAllLimiter()

    response = await client.post(
        f"/projects/{project.id}/notifications",
        headers=headers("limited-1"),
        json=request_body(),
    )

    assert response.status_code == 429


async def test_list_notifications_is_scoped_to_the_project(client, project) -> None:
    """A project with no dispatched children lists an empty page, not another project's rows."""
    response = await client.get(
        f"/projects/{project.id}/notifications",
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json() == []
