"""End-to-end dashboard journeys for multi-channel content.

Each test accepts a notification through the real API, runs the intake
processor (the API only queues it), and then delivers the resulting children
through recording providers. The assertions are about the contract the
dashboard depends on: one request can produce an email and an in-app
notification, templates are rendered through Liquid, and plain-text-only
content stays plain text.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from tiber.application.ports.channel_provider import ProviderResult
from tiber.application.services.delivery import NotificationDeliveryProcessor
from tiber.application.services.intake_processor import IntakeProcessor
from tiber.application.services.template import NotificationTemplateResolver
from tiber.domain.enums import DeliveryChannel, NotificationStatus
from tiber.domain.policies import PolicyResolver
from tiber.infrastructure.ai.fallback import FallbackDecisionEngine
from tiber.infrastructure.models import RecipientModel
from tiber.infrastructure.repositories.sqlalchemy_delivery_attempt_repository import (
    SQLAlchemyDeliveryAttemptRepository,
)
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
BOTH_CHANNELS = ["email", "in_app"]


class _Outbox:
    """Intake fan-out outbox that does not enqueue delivery jobs."""

    async def enqueue_dispatch(self, notification) -> None:
        return None


class _RecordingProvider:
    """Capture exactly what the delivery processor hands to a provider."""

    def __init__(self, channel: DeliveryChannel) -> None:
        self.channel = channel
        self.name = f"recording-{channel.value}"
        self.calls: list[dict] = []

    async def send(
        self,
        recipient_address: str,
        title: str | None,
        body: str,
        actions=(),
        images=(),
        metadata: dict | None = None,
        html_body: str | None = None,
    ) -> ProviderResult:
        self.calls.append(
            {
                "recipient_address": recipient_address,
                "title": title,
                "body": body,
                "html_body": html_body,
                "metadata": metadata,
            }
        )
        return ProviderResult(success=True, provider_message_id=f"{self.name}-id")

    async def health_check(self) -> bool:
        return True


def _headers(idempotency_key: str) -> dict:
    return {**AUTH, "Idempotency-Key": idempotency_key}


async def _recipient(session, project_id: UUID, external_id: str) -> RecipientModel:
    recipient = RecipientModel(
        project_id=project_id,
        external_id=external_id,
        addresses={"email": f"{external_id}@example.com", "in_app": external_id},
    )
    session.add(recipient)
    await session.commit()
    return recipient


async def _process(session, project_id: UUID, transaction_id: UUID):
    intake = await SQLAlchemyNotificationIntakeRepository(
        session
    ).get_by_transaction_id(transaction_id, project_id)
    assert intake is not None

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
    return await SQLAlchemyNotificationRepository(session).list_by_transaction_id(
        transaction_id, project_id
    )


async def _deliver(session, project_id: UUID, notifications):
    providers = {
        DeliveryChannel.EMAIL: _RecordingProvider(DeliveryChannel.EMAIL),
        DeliveryChannel.IN_APP: _RecordingProvider(DeliveryChannel.IN_APP),
    }
    for notification in notifications:
        processor = NotificationDeliveryProcessor(
            unit_of_work=SqlAlchemyUnitOfWork(session),
            notification_repository=SQLAlchemyNotificationRepository(session),
            recipient_repository=SQLAlchemyRecipientRepository(session),
            delivery_attempt_repository=SQLAlchemyDeliveryAttemptRepository(session),
            provider=providers[notification.channel],
        )
        delivered = await processor.process(notification.id, project_id=project_id)
        assert delivered.status is NotificationStatus.DELIVERED
    return providers


async def _create_template(client, project_id: UUID, name: str, variants: list[dict]):
    response = await client.post(
        f"/v1/projects/{project_id}/templates",
        headers=AUTH,
        json={"name": name, "variants": variants},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_builtin_single_channel_preset_cannot_fan_out_to_both_channels(
    client,
    project,
    session,
) -> None:
    """A preset is one variant, so naming both channels fails at accept time."""
    project_id = project.id
    await _recipient(session, project_id, "preset-gap")

    created = await client.post(
        f"/v1/projects/{project_id}/templates",
        headers=AUTH,
        json={"name": "Default email only", "preset_id": "email-starter"},
    )
    assert created.status_code == 201

    response = await client.post(
        f"/v1/projects/{project_id}/notifications",
        headers=_headers("preset-gap-1"),
        json={
            "recipient_id": "preset-gap",
            "channels": BOTH_CHANNELS,
            "template_slug": created.json()["template_slug"],
            "template_variables": {
                "subject": "Statement ready",
                "heading": "Hello",
                "body": "Open the app",
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["error"] == "channel_not_available"
    assert "no variant" in response.json()["message"]


async def test_combined_template_fans_out_to_email_and_in_app(
    client,
    project,
    session,
) -> None:
    """One request with a two-variant template produces a child per channel."""
    project_id = project.id
    await _recipient(session, project_id, "combined")

    presets = (
        await client.get(f"/v1/projects/{project_id}/template-presets", headers=AUTH)
    ).json()
    preset = {item["id"]: item["variant"] for item in presets}
    template = await _create_template(
        client,
        project_id,
        "Combined starter",
        [
            {"channel": "email", "content": preset["email-starter"]["content"]},
            {"channel": "in_app", "content": preset["in-app-starter"]["content"]},
        ],
    )

    accepted = await client.post(
        f"/v1/projects/{project_id}/notifications",
        headers=_headers("combined-1"),
        json={
            "recipient_id": "combined",
            "channels": BOTH_CHANNELS,
            "category": "informational",
            "template_slug": template["template_slug"],
            "template_variables": {
                "subject": "Statement ready",
                "heading": "Hello Ada",
                "body": "<p>Open the app</p>",
            },
        },
    )
    assert accepted.status_code == 202, accepted.text

    children = await _process(
        session, project_id, UUID(accepted.json()["transaction_id"])
    )
    assert {child.channel for child in children} == {
        DeliveryChannel.EMAIL,
        DeliveryChannel.IN_APP,
    }
    by_channel = {child.channel: child for child in children}
    assert by_channel[DeliveryChannel.EMAIL].content.title == "Statement ready"
    assert "Hello Ada" in by_channel[DeliveryChannel.EMAIL].content.html_body
    assert "<p>Open the app</p>" in (
        by_channel[DeliveryChannel.EMAIL].content.html_body
    )
    assert "Hello Ada" in by_channel[DeliveryChannel.IN_APP].content.html_body
    assert "<p>Open the app</p>" in (
        by_channel[DeliveryChannel.IN_APP].content.html_body
    )

    providers = await _deliver(session, project_id, children)
    assert providers[DeliveryChannel.EMAIL].calls[0]["title"] == "Statement ready"
    assert (
        "<p>Open the app</p>"
        in (providers[DeliveryChannel.EMAIL].calls[0]["html_body"])
    )
    assert (
        "<p>Open the app</p>"
        in (providers[DeliveryChannel.IN_APP].calls[0]["html_body"])
    )


async def test_direct_html_renders_to_email_and_in_app(
    client,
    project,
    session,
) -> None:
    """Direct content is Liquid source too, and can target both channels."""
    project_id = project.id
    await _recipient(session, project_id, "direct")

    accepted = await client.post(
        f"/v1/projects/{project_id}/notifications",
        headers=_headers("direct-1"),
        json={
            "recipient_id": "direct",
            "channels": BOTH_CHANNELS,
            "category": "informational",
            "content": {
                "title": "Hello {{ name }}",
                "html_body": "<main><h1>{{ name }}</h1></main>",
            },
            "template_variables": {"name": "Ada"},
        },
    )
    assert accepted.status_code == 202, accepted.text

    children = await _process(
        session, project_id, UUID(accepted.json()["transaction_id"])
    )
    assert {child.channel for child in children} == {
        DeliveryChannel.EMAIL,
        DeliveryChannel.IN_APP,
    }
    by_channel = {child.channel: child for child in children}
    # Title is the email subject; the in-app child stores no subject.
    assert by_channel[DeliveryChannel.EMAIL].content.title == "Hello Ada"
    assert by_channel[DeliveryChannel.IN_APP].content.title is None
    for child in children:
        assert child.content.html_body == "<main><h1>Ada</h1></main>"

    providers = await _deliver(session, project_id, children)
    assert providers[DeliveryChannel.EMAIL].calls[0]["title"] == "Hello Ada"
    assert providers[DeliveryChannel.IN_APP].calls[0]["title"] is None
    for channel in (DeliveryChannel.EMAIL, DeliveryChannel.IN_APP):
        assert providers[channel].calls[0]["html_body"] == ("<main><h1>Ada</h1></main>")


async def test_plain_text_direct_content_stays_plain_text(
    client,
    project,
    session,
) -> None:
    """Plain-text-only direct content works on email and in-app."""
    project_id = project.id
    await _recipient(session, project_id, "plain-direct")

    accepted = await client.post(
        f"/v1/projects/{project_id}/notifications",
        headers=_headers("plain-direct-1"),
        json={
            "recipient_id": "plain-direct",
            "channels": BOTH_CHANNELS,
            "category": "informational",
            "content": {
                "title": "Hello {{ name }}",
                "plain_text_body": "Your code is {{ code }}.",
            },
            "template_variables": {"name": "Ada", "code": "1234"},
        },
    )
    assert accepted.status_code == 202, accepted.text

    children = await _process(
        session, project_id, UUID(accepted.json()["transaction_id"])
    )
    assert len(children) == 2
    by_channel = {child.channel: child for child in children}
    assert by_channel[DeliveryChannel.EMAIL].content.title == "Hello Ada"
    assert by_channel[DeliveryChannel.IN_APP].content.title is None
    for child in children:
        assert child.content.plain_text_body == "Your code is 1234."
        assert child.content.html_body is None

    providers = await _deliver(session, project_id, children)
    assert providers[DeliveryChannel.EMAIL].calls[0]["title"] == "Hello Ada"
    assert providers[DeliveryChannel.IN_APP].calls[0]["title"] is None
    for channel in (DeliveryChannel.EMAIL, DeliveryChannel.IN_APP):
        assert providers[channel].calls[0]["body"] == "Your code is 1234."
        assert providers[channel].calls[0]["html_body"] is None


async def test_plain_text_template_fans_out_to_email_and_in_app(
    client,
    project,
    session,
) -> None:
    """A saved template can be plain-text-only on both channels."""
    project_id = project.id
    await _recipient(session, project_id, "plain-template")

    template = await _create_template(
        client,
        project_id,
        "Plain text starter",
        [
            {
                "channel": "email",
                "content": {
                    "title": "Hello {{ name }}",
                    "plain_text_body": "Your code is {{ code }}.",
                },
            },
            {
                "channel": "in_app",
                "content": {"plain_text_body": "Your code is {{ code }}."},
            },
        ],
    )

    accepted = await client.post(
        f"/v1/projects/{project_id}/notifications",
        headers=_headers("plain-template-1"),
        json={
            "recipient_id": "plain-template",
            "channels": BOTH_CHANNELS,
            "category": "informational",
            "template_slug": template["template_slug"],
            "template_variables": {"name": "Ada", "code": "1234"},
        },
    )
    assert accepted.status_code == 202, accepted.text

    children = await _process(
        session, project_id, UUID(accepted.json()["transaction_id"])
    )
    assert len(children) == 2
    for child in children:
        assert child.content.plain_text_body == "Your code is 1234."
        assert child.content.html_body is None

    providers = await _deliver(session, project_id, children)
    for channel in (DeliveryChannel.EMAIL, DeliveryChannel.IN_APP):
        assert providers[channel].calls[0]["body"] == "Your code is 1234."
        assert providers[channel].calls[0]["html_body"] is None


async def test_edit_preset_template_replaces_variants_and_sends(
    client,
    project,
    session,
) -> None:
    """Flow 4: persist a preset, edit it, replace it, then send."""
    project_id = project.id
    await _recipient(session, project_id, "edited")

    created = await client.post(
        f"/v1/projects/{project_id}/templates",
        headers=AUTH,
        json={"name": "Email starter", "preset_id": "email-starter"},
    )
    assert created.status_code == 201
    template_id = created.json()["id"]

    edited = await client.put(
        f"/v1/projects/{project_id}/templates/{template_id}",
        headers=AUTH,
        json={
            "name": "Edited starter",
            "variants": [
                {
                    "channel": "email",
                    "content": {
                        "title": "Edited: {{ subject }}",
                        "html_body": "<h1>{{ heading }}</h1><div>{{ body }}</div>",
                    },
                },
                {
                    "channel": "in_app",
                    "content": {
                        "html_body": "<strong>{{ heading }}</strong>"
                        "<div>{{ body }}</div>"
                    },
                },
            ],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["template_slug"] == "edited-starter"
    assert {variant["channel"] for variant in edited.json()["variants"]} == {
        "email",
        "in_app",
    }

    accepted = await client.post(
        f"/v1/projects/{project_id}/notifications",
        headers=_headers("edited-1"),
        json={
            "recipient_id": "edited",
            "channels": BOTH_CHANNELS,
            "category": "informational",
            "template_slug": "edited-starter",
            "template_variables": {
                "subject": "Welcome",
                "heading": "Hello Ada",
                "body": "Open the app",
            },
        },
    )
    assert accepted.status_code == 202, accepted.text

    children = await _process(
        session, project_id, UUID(accepted.json()["transaction_id"])
    )
    by_channel = {child.channel: child for child in children}
    assert by_channel[DeliveryChannel.EMAIL].content.title == "Edited: Welcome"
    assert "<h1>Hello Ada</h1>" in (by_channel[DeliveryChannel.EMAIL].content.html_body)
    assert "<strong>Hello Ada</strong>" in (
        by_channel[DeliveryChannel.IN_APP].content.html_body
    )

    await session.refresh(project)
    replaced = await client.put(
        f"/v1/projects/{project_id}/templates/{template_id}",
        headers=AUTH,
        json={
            "name": "Edited starter",
            "variants": [
                {
                    "channel": "in_app",
                    "content": {"plain_text_body": "Only in-app now"},
                }
            ],
        },
    )
    assert replaced.status_code == 200
    assert [variant["channel"] for variant in replaced.json()["variants"]] == ["in_app"]
