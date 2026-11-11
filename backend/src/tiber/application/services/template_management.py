"""Use cases for project templates and reusable brand profiles."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.domain.entities import BrandProfile, Template
from tiber.domain.enums import DeliveryChannel
from tiber.domain.exceptions import (
    EntityNotFoundError,
    InvalidEntityAttributeError,
    TemplateChannelMismatchError,
)
from tiber.domain.repositories import BrandProfileRepository, TemplateRepository
from tiber.domain.services import TemplateRenderer
from tiber.domain.value_objects import NotificationContent, TemplateVariant

from .template import DEFAULT_BRAND_TOKENS


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


_PRESETS = (
    TemplatePreset(
        id="email-starter",
        name="Styled email starter",
        variant=TemplateVariant(
            channel=DeliveryChannel.EMAIL,
            content=NotificationContent(
                title="{{subject}}",
                html_body=(
                    '<!doctype html><html><head><meta charset="utf-8"></head>'
                    '<body style="margin:0;background:var(--tiber-background);'
                    'font-family:Arial,sans-serif;color:var(--tiber-text)">'
                    '<main style="max-width:600px;margin:32px auto;padding:32px;'
                    'background:var(--tiber-surface);border-radius:12px">'
                    '<h1 style="color:var(--tiber-primary)">{{heading}}</h1>'
                    "<div>{{body}}</div></main></body></html>"
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
                    '<article style="padding:16px;border-left:4px solid '
                    "var(--tiber-primary);background:var(--tiber-surface);"
                    'color:var(--tiber-text)"><strong>{{heading}}</strong>'
                    '<div style="color:var(--tiber-muted)">{{body}}</div></article>'
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
        brand_profile_repository: BrandProfileRepository,
        renderer: TemplateRenderer | None = None,
    ) -> None:
        """Initialize project template use cases."""
        self._uow = unit_of_work
        self._templates = template_repository
        self._brand_profiles = brand_profile_repository
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
        brand_profile_id: UUID | None = None,
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
        await self._validate_brand_profile(project_id, brand_profile_id)
        template = Template.create(
            project_id=project_id,
            name=name,
            variants=variants,
            brand_profile_id=brand_profile_id,
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
        limit: int,
        offset: int,
        channel: DeliveryChannel | None = None,
    ) -> list[Template]:
        """List templates for a project."""
        return await self._templates.list_by_project(project_id, limit, offset, channel)

    async def update(
        self,
        *,
        project_id: UUID,
        template_id: UUID,
        name: str,
        variants: list[TemplateVariant],  # type: ignore  # mypy conflates list method with list type
        brand_profile_id: UUID | None,
    ) -> Template:
        """Replace all editable template properties."""
        template = await self.get(project_id, template_id)
        await self._validate_brand_profile(project_id, brand_profile_id)
        updated = template.update(
            name=name,
            variants=variants,
            brand_profile_id=brand_profile_id,
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
        """Render a variant with supplied values and project brand tokens."""
        template = await self.get(project_id, template_id)
        variant = template.variants.get(channel)
        if variant is None:
            available = ", ".join(sorted(ch.value for ch in template.variants))
            raise TemplateChannelMismatchError(
                str(template_id), available or "none", channel.value
            )
        brand_tokens = DEFAULT_BRAND_TOKENS
        if template.brand_profile_id is not None:
            profile = await self._brand_profiles.get_by_id(
                template.brand_profile_id, project_id
            )
            if profile is None:
                raise EntityNotFoundError(BrandProfile, str(template.brand_profile_id))
            brand_tokens = DEFAULT_BRAND_TOKENS | profile.tokens
        return RenderedTemplatePreview(
            content=self._renderer.render(variant, variables, brand_tokens),
            required_variables=variant.variables,
        )

    async def _validate_brand_profile(
        self, project_id: UUID, brand_profile_id: UUID | None
    ) -> None:
        if brand_profile_id is None:
            return
        profile = await self._brand_profiles.get_by_id(brand_profile_id, project_id)
        if profile is None:
            raise EntityNotFoundError(BrandProfile, str(brand_profile_id))


class BrandProfileManagementService:
    """Manage visual design tokens within a project."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        brand_profile_repository: BrandProfileRepository,
    ) -> None:
        """Initialize brand profile use cases."""
        self._uow = unit_of_work
        self._profiles = brand_profile_repository

    async def create(
        self, *, project_id: UUID, name: str, tokens: dict[str, str]
    ) -> BrandProfile:
        """Create a project-scoped profile."""
        profile = BrandProfile.create(project_id=project_id, name=name, tokens=tokens)
        async with self._uow:
            return await self._profiles.save(profile)

    async def get(self, project_id: UUID, profile_id: UUID) -> BrandProfile:
        """Get a profile scoped to its owning project."""
        profile = await self._profiles.get_by_id(profile_id, project_id)
        if profile is None:
            raise EntityNotFoundError(BrandProfile, str(profile_id))
        return profile

    async def list(
        self, project_id: UUID, *, limit: int, offset: int
    ) -> list[BrandProfile]:
        """List a project's profiles."""
        return await self._profiles.list_by_project(project_id, limit, offset)

    async def update(
        self,
        *,
        project_id: UUID,
        profile_id: UUID,
        name: str,
        tokens: dict[str, str],
    ) -> BrandProfile:
        """Replace a profile's name and tokens."""
        profile = await self.get(project_id, profile_id)
        updated = profile.update(name=name, tokens=tokens)
        async with self._uow:
            return await self._profiles.save(updated)

    async def delete(self, project_id: UUID, profile_id: UUID) -> None:
        """Delete a profile; referencing templates become unbranded."""
        profile = await self.get(project_id, profile_id)
        async with self._uow:
            await self._profiles.delete(profile)
