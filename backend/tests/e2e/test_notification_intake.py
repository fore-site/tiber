"""End-to-end journeys for the accept half of the notification contract.

These drive the real ASGI app against a real Postgres database and assert only
what the HTTP contract promises: a 202 with a batch handle, replay safety,
conflict detection, request-status reads, rate limiting, and project scoping.

The HTML-content journey invokes the intake processor after acceptance so it
also verifies that authored HTML reaches the persisted notification.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from tiber.application.services.intake_processor import IntakeProcessor
from tiber.application.services.template import NotificationTemplateResolver
from tiber.domain.entities import Notification
from tiber.domain.enums import (
    DeliveryChannel,
    NotificationCategory,
    NotificationStatus,
    SendTimeBasis,
)
from tiber.domain.policies import PolicyResolver
from tiber.domain.value_objects import NotificationContent
from tiber.infrastructure.ai.fallback import FallbackDecisionEngine
from tiber.infrastructure.models import RecipientModel
from tiber.infrastructure.repositories.sqlalchemy_notification_intake_repository import (
    SQLAlchemyNotificationIntakeRepository,
)
from tiber.infrastructure.repositories.sqlalchemy_notification_repository import (
    SQLAlchemyNotificationRepository,
)
from tiber.infrastructure.repositories.sqlalchemy_notification_topic_repository import (
    SQLAlchemyNotificationTopicRepository,
)
from tiber.infrastructure.repositories.sqlalchemy_recipient_repository import (
    SQLAlchemyRecipientRepository,
)
from tiber.infrastructure.repositories.sqlalchemy_template_repository import (
    SQLAlchemyTemplateRepository,
)
from tiber.infrastructure.repositories.unit_of_work import SqlAlchemyUnitOfWork

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
            "plain_text_body": "Sign in to view it.",
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
    UUID(body["transaction_id"])
    assert response.headers["location"].endswith(
        f"/projects/{project.id}/notification-requests/{body['transaction_id']}"
    )


async def test_direct_html_is_included_in_the_accepted_intake(
    client,
    project,
    session,
) -> None:
    """Direct HTML survives request mapping and the intake persistence boundary."""
    project_id = project.id
    response = await client.post(
        f"/projects/{project_id}/notifications",
        headers=headers("direct-html-1"),
        json=request_body(
            content={
                "title": "Your statement is ready",
                "html_body": "<main><h1>Your statement is ready</h1></main>",
            }
        ),
    )

    assert response.status_code == 202
    intake = await SQLAlchemyNotificationIntakeRepository(
        session
    ).get_by_transaction_id(UUID(response.json()["transaction_id"]), project_id)
    assert intake is not None
    assert intake.payload.content is not None
    assert intake.payload.content.html_body == (
        "<main><h1>Your statement is ready</h1></main>"
    )

    changed_markup = await client.post(
        f"/projects/{project_id}/notifications",
        headers=headers("direct-html-1"),
        json=request_body(
            content={
                "title": "Your statement is ready",
                "html_body": "<main><h1>Different</h1></main>",
            }
        ),
    )
    assert changed_markup.status_code == 409
    assert changed_markup.json()["error"] == "idempotency_key_conflict"

    class _Outbox:
        async def enqueue_dispatch(self, notification) -> None:
            return None

    processor = IntakeProcessor(
        unit_of_work=SqlAlchemyUnitOfWork(session),
        intake_repository=SQLAlchemyNotificationIntakeRepository(session),
        notification_repository=SQLAlchemyNotificationRepository(session),
        recipient_repository=SQLAlchemyRecipientRepository(session),
        topic_repository=SQLAlchemyNotificationTopicRepository(session),
        template_resolver=NotificationTemplateResolver(
            SQLAlchemyTemplateRepository(session)
        ),
        policy_resolver=PolicyResolver(),
        decision_engine=FallbackDecisionEngine(),
        outbox=_Outbox(),
    )
    await processor.process(intake.id)

    stored = await SQLAlchemyNotificationRepository(session).list_by_transaction_id(
        intake.transaction_id, project_id
    )
    assert len(stored) == 1
    assert (
        stored[0].content.html_body == "<main><h1>Your statement is ready</h1></main>"
    )

    await session.refresh(project)
    status_response = await client.get(
        f"/projects/{project_id}/notification-requests/{intake.transaction_id}",
        headers=AUTH,
    )
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["status"] == "completed"
    assert status_body["notifications"][0]["content"]["html_body"] == (
        "<main><h1>Your statement is ready</h1></main>"
    )


async def test_direct_html_requires_an_email_or_in_app_channel(
    client,
    project,
) -> None:
    """Do not accept HTML that cannot be attached to any selected channel."""
    response = await client.post(
        f"/projects/{project.id}/notifications",
        headers=headers("direct-html-unsupported-channel"),
        json=request_body(
            email=None,
            push="push-token",
            content={
                "title": "Styled",
                "html_body": "<main>Styled content</main>",
            },
        ),
    )

    assert response.status_code == 422
    assert response.json()["error"] == "channel_not_available"


async def test_create_notification_topic_persists_project_topic(
    client,
    project,
    session,
) -> None:
    """Creating a topic returns its derived slug and persists it in the project."""
    response = await client.post(
        f"/projects/{project.id}/topics",
        headers=AUTH,
        json={"title": "Product Updates", "category": "informational"},
    )

    assert response.status_code == 201
    body = response.json()
    topic = await SQLAlchemyNotificationTopicRepository(session).get_by_slug(
        "product-updates", project.id
    )
    assert topic is not None
    assert body["id"] == str(topic.id)
    assert body["project_id"] == str(project.id)
    assert body["category"] == "informational"
    assert body["title"] == "Product Updates"
    assert body["topic_slug"] == "product-updates"

    duplicate = await client.post(
        f"/projects/{project.id}/topics",
        headers=AUTH,
        json={"title": "Product Updates", "category": "social"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "notification_topic_name_conflict"


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
    assert second.json()["transaction_id"] == first.json()["transaction_id"]
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
    transaction_id = accepted.json()["transaction_id"]

    response = await client.get(
        f"/projects/{project.id}/notification-requests/{transaction_id}",
        headers=AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transaction_id"] == transaction_id
    assert body["project_id"] == str(project.id)
    assert body["status"] in {"received", "processing"}
    assert body["notifications"] == []


async def test_rate_limited_project_is_rejected(client, app, project) -> None:
    """The project policy rejects the request and preserves its rate-limit headers."""
    from pycurb.core import RateLimitResult

    from tiber.api.dependencies import get_rate_limit_policies
    from tiber.core.redis import RedisKeys

    class _DenyingCoreLimiter:
        key: str | None = None
        rule_name: str | None = None

        async def check(self, key: str, rule_name: str) -> RateLimitResult:
            self.key = key
            self.rule_name = rule_name
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=1_700_000_060,
                limit=100,
                retry_after=60,
            )

    class _DenyingPolicies:
        def __init__(self) -> None:
            self.limiter = _DenyingCoreLimiter()

    policies = _DenyingPolicies()
    app.dependency_overrides[get_rate_limit_policies] = lambda: policies

    response = await client.post(
        f"/projects/{project.id}/notifications",
        headers=headers("limited-1"),
        json=request_body(),
    )

    assert response.status_code == 429
    assert response.headers["x-ratelimit-limit"] == "100"
    assert response.headers["x-ratelimit-remaining"] == "0"
    assert response.headers["retry-after"] == "60"
    assert policies.limiter.key == RedisKeys.rate_limit("api", str(project.id))
    assert policies.limiter.rule_name == "api"


async def test_list_notifications_is_scoped_to_the_project(client, project) -> None:
    """A project with no dispatched children lists an empty page, not another project's rows."""
    response = await client.get(
        f"/projects/{project.id}/notifications",
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json() == []


async def test_cancel_pending_notification_and_reject_repeat(
    client,
    project,
    session,
) -> None:
    """Cancellation persists, and repeat cancellation returns a conflict."""
    project_id = project.id
    recipient = RecipientModel(
        project_id=project_id,
        addresses={"email": "scheduled@example.com"},
    )
    session.add(recipient)
    await session.commit()

    notification = Notification.create(
        project_id=project_id,
        recipient_id=recipient.id,
        transaction_id=uuid4(),
        channel=DeliveryChannel.EMAIL,
        category=NotificationCategory.INFORMATIONAL,
        content=NotificationContent(title="Scheduled", plain_text_body="A message"),
        send_at=datetime.now(UTC) + timedelta(hours=1),
        send_time_basis=SendTimeBasis.EXPLICIT,
    )
    async with SqlAlchemyUnitOfWork(session):
        await SQLAlchemyNotificationRepository(session).save(notification)

    cancellation_url = (
        f"/projects/{project_id}/notifications/{notification.id}/cancellation"
    )
    cancelled = await client.put(cancellation_url, headers=AUTH)
    assert cancelled.status_code == 204

    fetched = await client.get(
        f"/projects/{project_id}/notifications/{notification.id}",
        headers=AUTH,
    )
    assert fetched.status_code == 200
    assert fetched.json()["status"] == NotificationStatus.CANCELLED.value

    repeated = await client.put(cancellation_url, headers=AUTH)
    assert repeated.status_code == 409

    await session.refresh(project)
    missing = await client.put(
        f"/projects/{project_id}/notifications/{uuid4()}/cancellation",
        headers=AUTH,
    )
    assert missing.status_code == 404
