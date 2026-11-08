"""Template variables: how a template declares them versus how they are used.

A template declares its variables implicitly, as ``{{name}}`` placeholders in
its content. Accept time asks "can this channel render, and which variables does
it need?"; render time substitutes exactly those placeholders. These tests pin
the two together, and pin the accept path's repository call to ``(slug,
project_id)`` so the scoping arguments cannot silently swap.
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
from tiber.domain.exceptions import (
    ChannelNotAvailableError,
    EntityNotFoundError,
    InvalidEntityAttributeError,
    TemplateRenderError,
)
from tiber.domain.services import TemplateRenderer
from tiber.domain.services.decision_constraints import compute_constraints
from tiber.domain.value_objects import NotificationContent, TemplateVariant
from tiber.domain.value_objects.placeholders import extract_placeholders


def make_template(*variants: TemplateVariant, name: str = "order-update") -> Template:
    """Build a template from the given variants."""
    return Template.create(project_id=uuid4(), name=name, variants=list(variants))


def email_variant(title: str, body: str) -> TemplateVariant:
    """Build an email variant (email requires a title)."""
    return TemplateVariant(
        channel=DeliveryChannel.EMAIL,
        content=NotificationContent(title=title, plain_text_body=body),
    )


def sms_variant(body: str) -> TemplateVariant:
    """Build an SMS variant (SMS forbids a title)."""
    return TemplateVariant(
        channel=DeliveryChannel.SMS,
        content=NotificationContent(plain_text_body=body),
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


# --- Variables are derived from the variants ---


def test_variant_reports_only_its_own_placeholders():
    """Variables are per variant, not per template."""
    assert sms_variant("Code: {{code}}").variables == frozenset({"code"})


def test_variant_without_placeholders_requires_nothing():
    """Static content needs no variables at all."""
    assert sms_variant("Maintenance tonight").variables == frozenset()


def test_template_variables_are_per_channel():
    """Email and SMS can need different variables for the same template."""
    template = make_template(
        email_variant("Hi {{first_name}}", "Order {{order_id}} for {{first_name}}"),
        sms_variant("Code: {{code}}"),
    )

    assert template.variables_for(DeliveryChannel.EMAIL) == frozenset(
        {"first_name", "order_id"}
    )
    assert template.variables_for(DeliveryChannel.SMS) == frozenset({"code"})


def test_required_variables_is_the_union_across_variants():
    """The template-wide union is a superset of any single channel's needs."""
    template = make_template(
        email_variant("Hi {{first_name}}", "Body"),
        sms_variant("Code: {{code}}"),
    )

    assert template.required_variables == frozenset({"first_name", "code"})


def test_required_variables_of_an_empty_template_is_empty():
    """No variants means no variables, not an error."""
    assert make_template().required_variables == frozenset()


def test_variables_for_an_absent_channel_raises():
    """Asking a template for a channel it has no variant for is a bug, not a miss."""
    template = make_template(sms_variant("Body"))

    with pytest.raises(InvalidEntityAttributeError):
        template.variables_for(DeliveryChannel.EMAIL)


def test_variables_cannot_go_stale_after_a_variant_changes():
    """Deriving variables on demand is why there is nothing to invalidate."""
    template = make_template(sms_variant("Hi {{first_name}}"))
    changed = template.add_or_update_variants(sms_variant("Hi {{nickname}}"))

    assert changed.variables_for(DeliveryChannel.SMS) == frozenset({"nickname"})
    assert template.variables_for(DeliveryChannel.SMS) == frozenset({"first_name"})


def test_variables_disappear_with_the_variant():
    """Removing a variant removes its variables from the union."""
    template = make_template(
        email_variant("Hi {{first_name}}", "Body"),
        sms_variant("Code: {{code}}"),
    )

    assert template.remove_variant(DeliveryChannel.EMAIL).required_variables == (
        frozenset({"code"})
    )


# --- The renderer reads placeholders the same way ---


def test_renderer_substitutes_a_variable_the_entity_counted():
    """Accept-time and render-time agree on the placeholder syntax."""
    variant = sms_variant("Hi {{ first_name }}")

    rendered = TemplateRenderer().render(variant, {"first_name": "Ada"})

    assert rendered.plain_text_body == "Hi Ada"


def test_renderer_rejects_a_missing_variable_the_entity_counted():
    """A variable the entity required cannot silently render as empty."""
    variant = sms_variant("Hi {{first_name}}")

    with pytest.raises(TemplateRenderError):
        TemplateRenderer().render(variant, {})


# --- Accept-time constraints use the same per-channel variables ---


def test_constraints_accept_a_channel_whose_variables_are_provided():
    """Feasibility is judged per channel, using only that variant's variables."""
    constraints = compute_constraints(
        available_channels=frozenset({DeliveryChannel.EMAIL, DeliveryChannel.SMS}),
        adhoc=False,
        requested_channels=None,
        opted_out=frozenset(),
        client_category=None,
        template=make_template(
            email_variant("Hi {{first_name}}", "Body"),
            sms_variant("Code: {{code}}"),
        ),
        # Only the variables SMS needs: email stays infeasible, SMS does not.
        template_variables={"code": "1234"},
        content=None,
    )

    assert constraints.feasible_channels == frozenset({DeliveryChannel.SMS})


def test_constraints_reject_a_channel_the_template_has_no_variant_for():
    """A client-named channel with no variant fails the whole request."""
    with pytest.raises(ChannelNotAvailableError, match="no variant for this channel"):
        compute_constraints(
            available_channels=frozenset({DeliveryChannel.EMAIL}),
            adhoc=False,
            requested_channels=[DeliveryChannel.EMAIL],
            opted_out=frozenset(),
            client_category=None,
            template=make_template(sms_variant("Body")),
            template_variables=None,
            content=None,
        )


# --- The accept path asks the repository by slug, then reads the entity ---


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

    loaded = await make_service(repository)._require_template(cmd)

    assert repository.calls == [(cmd.template_slug, cmd.project_id)]
    assert loaded is template
    assert loaded.variables_for(DeliveryChannel.SMS) == frozenset({"first_name"})


async def test_accept_lookup_raises_for_an_unknown_slug():
    """A missing template is a 422-level domain error, named by the entity."""
    service = make_service(FakeTemplateRepository(None))

    with pytest.raises(EntityNotFoundError):
        await service._require_template(make_command(template_slug="missing"))
