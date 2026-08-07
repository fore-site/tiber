"""Tests for template rendering and the template resolver.

Pure-Python tests using an in-memory template repository fake - no database
or broker required.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tiber.application.services import NotificationTemplateResolver
from tiber.domain.entities import Notification, Template
from tiber.domain.enums import DeliveryChannel
from tiber.domain.exceptions import (
    ProjectScopeViolationError,
    TemplateChannelMismatchError,
    TemplateNotFoundError,
)
from tiber.domain.services import TemplateRenderer
from tiber.domain.value_objects import NotificationContent


class FakeTemplateRepository:
    """In-memory TemplateRepository backed by a mapping of templates."""

    def __init__(self, templates: dict | None = None) -> None:
        """Initialize the store."""
        self._store = templates or {}

    async def save(self, template: Template) -> Template:
        """Persist a template."""
        self._store[template.id] = template
        return template

    async def get_by_id(self, id):
        """Get a template by ID."""
        return self._store.get(id)

    async def get_by_slug(self, project_id, slug):
        """Get a template for a project by slug."""
        for t in self._store.values():
            if t.project_id == project_id and t.slug == slug:
                return t
        return None

    async def list_by_project(self, project_id, limit, offset):
        """List templates for a project."""
        items = [t for t in self._store.values() if t.project_id == project_id]
        return items[offset : offset + limit]


def make_template(
    *,
    project_id=None,
    channel=DeliveryChannel.EMAIL,
    body="Hi {{name}}",
    subject="Hello {{name}}",
) -> Template:
    """Build a template; subject is only valid for the email channel."""
    return Template(
        id=uuid4(),
        project_id=project_id or uuid4(),
        name="welcome",
        slug="welcome",
        channel=channel,
        body=body,
        subject=subject if channel == DeliveryChannel.EMAIL else None,
    )


def make_notification(
    *,
    project_id,
    template_id=None,
    variables=None,
    channel=DeliveryChannel.EMAIL,
) -> Notification:
    """Build a pending notification referencing an optional template."""
    return Notification(
        id=uuid4(),
        project_id=project_id,
        recipient_id=uuid4(),
        correlation_id=uuid4(),
        channel=channel,
        content=NotificationContent(subject="Direct", body="Direct body"),
        template_id=template_id,
        template_variables=variables,
    )


# --- TemplateRenderer (pure rendering) ---


def test_render_substitutes_variables():
    """Present variables are substituted into subject and body."""
    template = make_template(body="Hi {{name}}, code {{code}}", subject="For {{name}}")
    rendered = TemplateRenderer().render(template, {"name": "Ada", "code": 1234})

    assert rendered.body == "Hi Ada, code 1234"
    assert rendered.subject == "For Ada"


def test_render_missing_variable_becomes_empty_string():
    """A placeholder without a variable value renders as empty, not a crash."""
    template = make_template(body="Hi {{name}} {{missing}}")
    rendered = TemplateRenderer().render(template, {"name": "Ada"})

    assert rendered.body == "Hi Ada "


def test_render_handles_whitespace_inside_braces():
    """Placeholders tolerate whitespace around the variable name."""
    template = make_template(body="Hi {{ name }}!")
    rendered = TemplateRenderer().render(template, {"name": "Ada"})

    assert rendered.body == "Hi Ada!"


def test_render_no_variables_passes_body_through():
    """A template with no placeholders renders unchanged."""
    template = make_template(body="Static body", subject="Static subject")
    rendered = TemplateRenderer().render(template, None)

    assert rendered.body == "Static body"
    assert rendered.subject == "Static subject"


# --- NotificationTemplateResolver ---


async def test_resolver_falls_back_to_direct_content():
    """A notification without a template keeps its direct content."""
    project_id = uuid4()
    notification = make_notification(project_id=project_id, template_id=None)
    resolver = NotificationTemplateResolver(FakeTemplateRepository())

    content = await resolver.resolve_content(notification)

    assert content == notification.content


async def test_resolver_renders_template_content():
    """A valid template is rendered from the notification's variables."""
    project_id = uuid4()
    template = make_template(project_id=project_id, body="Welcome {{name}}!")
    repo = FakeTemplateRepository({template.id: template})
    resolver = NotificationTemplateResolver(repo)

    notification = make_notification(
        project_id=project_id,
        template_id=template.id,
        variables={"name": "Ada"},
    )
    content = await resolver.resolve_content(notification)

    assert content.body == "Welcome Ada!"
    assert content.subject == "Hello Ada"


async def test_resolver_raises_when_template_missing():
    """A referenced template that does not exist raises TemplateNotFoundError."""
    project_id = uuid4()
    resolver = NotificationTemplateResolver(FakeTemplateRepository())
    notification = make_notification(project_id=project_id, template_id=uuid4())

    with pytest.raises(TemplateNotFoundError):
        await resolver.resolve_content(notification)


async def test_resolver_rejects_cross_project_template():
    """A template owned by another project is rejected as a scope violation."""
    template = make_template(project_id=uuid4())
    repo = FakeTemplateRepository({template.id: template})
    resolver = NotificationTemplateResolver(repo)

    notification = make_notification(
        project_id=uuid4(),  # different project than the template
        template_id=template.id,
    )

    with pytest.raises(ProjectScopeViolationError):
        await resolver.resolve_content(notification)


async def test_resolver_rejects_channel_mismatch():
    """A template for a different channel than the notification is rejected."""
    project_id = uuid4()
    template = make_template(project_id=project_id, channel=DeliveryChannel.PUSH)
    repo = FakeTemplateRepository({template.id: template})
    resolver = NotificationTemplateResolver(repo)

    notification = make_notification(
        project_id=project_id,  # matching project
        template_id=template.id,
        channel=DeliveryChannel.EMAIL,  # mismatched channel
    )

    with pytest.raises(TemplateChannelMismatchError):
        await resolver.resolve_content(notification)
