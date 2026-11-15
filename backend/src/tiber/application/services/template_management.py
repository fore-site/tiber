"""Use cases for project templates."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tiber.application.pagination import (
    CursorPage,
    decode_time_id_cursor,
    encode_cursor,
)
from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.domain.entities import Template
from tiber.domain.enums import DeliveryChannel
from tiber.domain.exceptions import (
    EntityNotFoundError,
    InvalidEntityAttributeError,
    TemplateChannelMismatchError,
)
from tiber.domain.repositories import TemplateRepository
from tiber.domain.services import TemplateRenderer, content_for_channel
from tiber.domain.value_objects import NotificationContent, TemplateVariant


@dataclass(frozen=True)
class TemplatePreset:
    """A selectable starter variant for a channel."""

    id: str
    name: str
    variant: TemplateVariant


@dataclass(frozen=True)
class RenderedTemplatePreview:
    """Rendered content preview of one template variant."""

    content: NotificationContent
    required_variables: frozenset[str]


# Presets are ordinary templates with the colours written out. They used to
# reference ``var(--tiber-*)`` tokens injected from a brand profile; with that
# system gone, a preset has to be self-contained to render anywhere.
_PRESETS = (
    TemplatePreset(
        id="email-starter",
        name="Styled email starter",
        variant=TemplateVariant(
            channel=DeliveryChannel.EMAIL,
            content=NotificationContent(
                title="{{ subject | escape }}",
                html_body=(
                    '<!doctype html><html><head><meta charset="utf-8"></head>'
                    '<body style="margin:0;background:#f4f6fb;'
                    'font-family:Arial,sans-serif;color:#182230">'
                    '<main style="max-width:600px;margin:32px auto;padding:32px;'
                    'background:#ffffff;border-radius:12px">'
                    '<h1 style="color:#3157d5">{{ heading | escape }}</h1>'
                    "<div>{{ body }}</div></main></body></html>"
                ),
            ),
        ),
    ),
    TemplatePreset(
        id="in-app-starter",
        name="Styled in-app starter",
        variant=TemplateVariant(
            channel=DeliveryChannel.IN_APP,
            content=NotificationContent(
                html_body=(
                    '<article style="padding:16px;border-left:4px solid #3157d5;'
                    'background:#ffffff;color:#182230">'
                    "<strong>{{ heading | escape }}</strong>"
                    '<div style="color:#667085">{{ body }}</div></article>'
                ),
            ),
        ),
    ),
)


class TemplateManagementService:
    """Manage templates and render previews within a project."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        template_repository: TemplateRepository,
        renderer: TemplateRenderer | None = None,
    ) -> None:
        """Initialize project template use cases."""
        self._uow = unit_of_work
        self._templates = template_repository
        self._renderer = renderer or TemplateRenderer()

    @staticmethod
    def presets() -> tuple[TemplatePreset, ...]:
        """Return the available non-persisted starter presets."""
        return _PRESETS

    async def create(
        self,
        *,
        project_id: UUID,
        name: str,
        variants: list[TemplateVariant] | None = None,
        preset_id: str | None = None,
    ) -> Template:
        """Create a template from variants or one selected starter preset."""
        if preset_id is not None:
            preset = next((p for p in _PRESETS if p.id == preset_id), None)
            if preset is None:
                raise InvalidEntityAttributeError(
                    f"Unknown template preset: {preset_id}"
                )
            if variants is not None:
                raise InvalidEntityAttributeError(
                    "Provide either variants or preset_id, not both"
                )
            variants = [preset.variant]
        if not variants:
            raise InvalidEntityAttributeError(
                "At least one variant or a preset_id is required"
            )
        template = Template.create(
            project_id=project_id,
            name=name,
            variants=variants,
        )
        async with self._uow:
            return await self._templates.save(template)

    async def get(self, project_id: UUID, template_id: UUID) -> Template:
        """Get a template scoped to its owning project."""
        template = await self._templates.get_by_id(template_id, project_id)
        if template is None:
            raise EntityNotFoundError(Template, str(template_id))
        return template

    async def list(
        self,
        project_id: UUID,
        *,
        limit: int = 50,
        cursor: str | None = None,
        channel: DeliveryChannel | None = None,
    ) -> CursorPage[Template]:
        """List a page of templates for a project, newest first."""
        after = decode_time_id_cursor(cursor, time_field="created_at")
        templates = await self._templates.list_by_project(
            project_id, limit + 1, cursor=after, channel=channel
        )
        items = templates[:limit]
        next_cursor = (
            encode_cursor(
                created_at=items[-1].created_at.isoformat(),
                id=items[-1].id,
            )
            if len(templates) > limit
            else None
        )
        return CursorPage(items=items, next_cursor=next_cursor)

    async def update(
        self,
        *,
        project_id: UUID,
        template_id: UUID,
        name: str,
        variants: list[TemplateVariant],  # type: ignore  # mypy conflates list method with list type
    ) -> Template:
        """Replace all editable template properties."""
        template = await self.get(project_id, template_id)
        updated = template.update(
            name=name,
            variants=variants,
        )
        async with self._uow:
            return await self._templates.save(updated)

    async def delete(self, project_id: UUID, template_id: UUID) -> None:
        """Delete a project template."""
        template = await self.get(project_id, template_id)
        async with self._uow:
            await self._templates.delete(template)

    async def preview(
        self,
        *,
        project_id: UUID,
        template_id: UUID,
        channel: DeliveryChannel,
        variables: dict[str, object],
    ) -> RenderedTemplatePreview:
        """Render a persisted variant with supplied values."""
        template = await self.get(project_id, template_id)
        variant = template.variants.get(channel)
        if variant is None:
            available = ", ".join(sorted(ch.value for ch in template.variants))
            raise TemplateChannelMismatchError(
                str(template_id), available or "none", channel.value
            )
        return self.preview_content(
            channel=channel,
            content=variant.content,
            variables=variables,
        )

    def preview_content(
        self,
        *,
        channel: DeliveryChannel,
        content: NotificationContent,
        variables: dict[str, object],
    ) -> RenderedTemplatePreview:
        """Render unsaved editor content exactly as the send path would.

        Stateless by design: nothing is loaded or written, so the dashboard can
        preview a draft before deciding to save it as a template or send it
        directly. The title is dropped for channels that do not persist a
        subject, matching the notification children the send path builds.
        """
        variant = TemplateVariant(channel=channel, content=content)
        rendered = self._renderer.render(variant, variables)
        return RenderedTemplatePreview(
            content=content_for_channel(channel, rendered),
            required_variables=variant.variables,
        )
