"""TemplateInfo is the accept-time projection of the Template aggregate.

Accepting a notification needs channel feasibility and required variables,
never the template bodies. These tests pin the projection to the entity so the
two cannot drift, and confirm the renderer reads placeholders the same way.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tiber.application.services.notification_intake import (
    AcceptNotificationCommand,
    NotificationIntakeService,
)
from tiber.domain.entities import Template
from tiber.domain.enums import DeliveryChannel
from tiber.domain.exceptions import EntityNotFoundError, TemplateRenderError
from tiber.domain.services import TemplateRenderer
from tiber.domain.value_objects import NotificationContent, TemplateVariant
from tiber.domain.value_objects.intake import TemplateInfo
from tiber.domain.value_objects.placeholders import extract_placeholders


def make_template(*variants: TemplateVariant, name: str = "order-update") -> Template:
    """Build a template from the given variants."""
    return Template.create(project_id=uuid4(), name=name, variants=list(variants))


def email_variant(title: str, body: str) -> TemplateVariant:
    """Build an email variant (email requires a title)."""
    return TemplateVariant(
        channel=DeliveryChannel.EMAIL,
        content=NotificationContent(title=title, body=body),
    )


def sms_variant(body: str) -> TemplateVariant:
    """Build an SMS variant (SMS forbids a title)."""
    return TemplateVariant(
        channel=DeliveryChannel.SMS,
        content=NotificationContent(body=body),
    )


# --- extract_placeholders ---


def test_extract_placeholders_reads_title_and_body_and_deduplicates():
    """A variable repeated in title and body is reported once."""
    placeholders = extract_placeholders(
        "Hi {{first_name}}", "{{first_name}}, your order {{order_id}} shipped"
    )

    assert placeholders == frozenset({"first_name", "order_id"})


def test_extract_placeholders_allows_inner_whitespace():
    """The syntax allows ``{{ name }}``; extraction must match the renderer."""
    assert extract_placeholders("Hi {{ first_name }}") == frozenset({"first_name"})


def test_extract_placeholders_ignores_none_and_empty_text():
    """An absent title (SMS) contributes nothing."""
    assert extract_placeholders(None, "") == frozenset()


def test_extract_placeholders_ignores_malformed_braces():
    """Unbalanced or empty braces are literal text, not variables."""
    assert extract_placeholders("{ not a var } and {{ }}") == frozenset()


# --- TemplateInfo.from_template ---


def test_from_template_reports_every_channel_with_a_variant():
    """Report exactly the set of channels that have a variant."""
    template = make_template(email_variant("Hi", "Body"), sms_variant("Body"))

    info = TemplateInfo.from_template(template)

    assert info.id == template.id
    assert info.slug == "order-update"
    assert info.channels == frozenset({DeliveryChannel.EMAIL, DeliveryChannel.SMS})


def test_from_template_computes_required_variables_per_channel():
    """Variables are per channel: email and SMS can need different ones."""
    template = make_template(
        email_variant("Hi {{first_name}}", "Order {{order_id}} for {{first_name}}"),
        sms_variant("Code: {{code}}"),
    )

    info = TemplateInfo.from_template(template)

    assert info.required_variables[DeliveryChannel.EMAIL] == frozenset(
        {"first_name", "order_id"}
    )
    assert info.required_variables[DeliveryChannel.SMS] == frozenset({"code"})


def test_from_template_reports_no_variables_for_static_content():
    """A template with no placeholders requires nothing."""
    info = TemplateInfo.from_template(make_template(sms_variant("Maintenance tonight")))

    assert info.required_variables[DeliveryChannel.SMS] == frozenset()
    assert info.channels == frozenset({DeliveryChannel.SMS})


def test_from_template_without_variants_has_no_feasible_channels():
    """An empty aggregate projects to an empty channel set, not an error."""
    info = TemplateInfo.from_template(make_template())

    assert info.channels == frozenset()
    assert info.required_variables == {}


def test_from_template_uses_the_persisted_slug():
    """A slug created independently of the name survives projection."""
    template = Template.create(
        project_id=uuid4(),
        name="Order Update",
        variants=[sms_variant("Body")],
    ).rename("Order Update v2")

    info = TemplateInfo.from_template(template)

    assert info.slug == "order-update-v2"


# --- The renderer reads placeholders the same way ---


def test_renderer_substitutes_a_variable_the_projection_counted():
    """Accept-time and render-time agree on the placeholder syntax."""
    variant = sms_variant("Hi {{ first_name }}")

    rendered = TemplateRenderer().render(variant, {"first_name": "Ada"})

    assert rendered.body == "Hi Ada"


def test_renderer_rejects_a_missing_variable_the_projection_counted():
    """A variable the projection required cannot silently render as empty."""
    variant = sms_variant("Hi {{first_name}}")

    with pytest.raises(TemplateRenderError):
        TemplateRenderer().render(variant, {})


# --- The accept path asks the repository by slug, then projects ---


class FakeTemplateRepository:
    """Stand-in that records how the service calls the repository."""

    def __init__(self, template: Template | None) -> None:
        """Store the template to return and start the call log."""
        self.template = template
        self.calls: list[tuple[str, object]] = []

    async def get_by_slug(self, slug: str, project_id):
        """Record the lookup and return the configured template."""
        self.calls.append((slug, project_id))
        return self.template


def make_command(*, template_slug: str = "order-update", project_id=None):
    """Build an accept command whose only exercised field is the template slug."""
    return AcceptNotificationCommand(
        project_id=project_id or uuid4(),
        recipient_id=None,
        addresses={},
        channels=None,
        category=None,
        topic_slug=None,
        template_slug=template_slug,
        template_variables={"first_name": "Ada"},
        content=None,
        group_key=None,
        send_at=None,
        idempotency_key=None,
    )


def make_service(repository: FakeTemplateRepository) -> NotificationIntakeService:
    """Build the service with only the template lookup wired."""
    return NotificationIntakeService(
        unit_of_work=None,
        intake_repository=None,
        outbox=None,
        recipient_resolution=None,
        template_repository=repository,
        topic_repository=None,
    )


async def test_accept_lookup_uses_slug_then_project_scope():
    """The repository call is (slug, project_id), not the reverse."""
    template = make_template(sms_variant("Hi {{first_name}}"))
    repository = FakeTemplateRepository(template)
    cmd = make_command()

    info = await make_service(repository)._require_template(cmd)

    assert repository.calls == [(cmd.template_slug, cmd.project_id)]
    assert info is not None
    assert info.id == template.id
    assert info.required_variables[DeliveryChannel.SMS] == frozenset({"first_name"})


async def test_accept_lookup_raises_for_an_unknown_slug():
    """A missing template is a 422-level domain error, named by the entity."""
    service = make_service(FakeTemplateRepository(None))

    with pytest.raises(EntityNotFoundError):
        await service._require_template(make_command(template_slug="missing"))
