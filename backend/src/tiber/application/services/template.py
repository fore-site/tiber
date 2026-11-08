"""Template resolution for notification content.

Resolves the final content of a notification at worker time: when the
notification references a template, the template is loaded through the
project-scoped lookup (ownership enforced by the repository contract), the
variant for the notification's channel is selected, and it is rendered with the
notification's variables. Notifications carrying direct content
(``template_id`` is None) pass through unchanged — the "direct content
fallback" path.
"""

from __future__ import annotations

from dataclasses import dataclass

from tiber.domain.entities import Notification, Template
from tiber.domain.entities.brand_profile import BrandProfile
from tiber.domain.exceptions import (
    EntityNotFoundError,
    TemplateChannelMismatchError,
)
from tiber.domain.repositories import BrandProfileRepository, TemplateRepository
from tiber.domain.services import TemplateRenderer
from tiber.domain.value_objects import NotificationContent

DEFAULT_BRAND_TOKENS = {
    "primary": "#3157d5",
    "background": "#f4f6fb",
    "surface": "#ffffff",
    "text": "#182230",
    "muted": "#667085",
}


@dataclass(frozen=True)
class ResolvedTemplateContent:
    """Rendered content for one notification."""

    content: NotificationContent


class NotificationTemplateResolver:
    """Resolve and render a notification's content from its template."""

    def __init__(
        self,
        template_repository: TemplateRepository,
        renderer: TemplateRenderer | None = None,
        brand_profile_repository: BrandProfileRepository | None = None,
    ) -> None:
        """Initialize the resolver with template and optional brand repositories."""
        self._templates = template_repository
        self._renderer = renderer or TemplateRenderer()
        self._brand_profiles = brand_profile_repository

    async def resolve(self, notification: Notification) -> ResolvedTemplateContent:
        """Return rendered text and HTML, with direct-content fallback."""
        if notification.template_id is None:
            return ResolvedTemplateContent(notification.content)

        template = await self._templates.get_by_id(
            notification.template_id, notification.project_id
        )
        if template is None:
            raise EntityNotFoundError(Template, str(notification.template_id))

        variant = template.variants.get(notification.channel)
        if variant is None:
            available = (
                ", ".join(sorted(ch.value for ch in template.variants)) or "none"
            )
            raise TemplateChannelMismatchError(
                str(notification.template_id),
                available,
                str(notification.channel.value),
            )

        brand_tokens = DEFAULT_BRAND_TOKENS
        if template.brand_profile_id is not None:
            if self._brand_profiles is None:
                raise RuntimeError(
                    "Brand profile repository is required for styled templates"
                )
            profile = await self._brand_profiles.get_by_id(
                template.brand_profile_id, notification.project_id
            )
            if profile is None:
                raise EntityNotFoundError(BrandProfile, str(template.brand_profile_id))
            brand_tokens = DEFAULT_BRAND_TOKENS | profile.tokens

        return ResolvedTemplateContent(
            content=self._renderer.render(
                variant,
                notification.template_variables,
                brand_tokens,
            ),
        )

    async def resolve_content(self, notification: Notification) -> NotificationContent:
        """Return only the rendered semantic content for compatibility."""
        return (await self.resolve(notification)).content
