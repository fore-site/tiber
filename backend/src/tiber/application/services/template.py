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

from tiber.domain.entities import Notification, Template
from tiber.domain.exceptions import (
    EntityNotFoundError,
    TemplateChannelMismatchError,
)
from tiber.domain.repositories import TemplateRepository
from tiber.domain.services import TemplateRenderer
from tiber.domain.value_objects import NotificationContent


class NotificationTemplateResolver:
    """Resolve and render a notification's content from its template."""

    def __init__(
        self,
        template_repository: TemplateRepository,
        renderer: TemplateRenderer | None = None,
    ) -> None:
        """Initialize the resolver with a template repository and renderer."""
        self._templates = template_repository
        self._renderer = renderer or TemplateRenderer()

    async def resolve_content(self, notification: Notification) -> NotificationContent:
        """Return the notification's content, rendering its template if any.

        Direct-content notifications have no template and are returned as-is.
        """
        if notification.template_id is None:
            return notification.content

        template = await self._templates.get_by_id(
            notification.template_id, notification.project_id
        )
        if template is None:
            raise EntityNotFoundError(Template, str(notification.template_id))

        # A template holds one variant per channel; the notification's channel
        # must have one. Accept-time validation guarantees it for requests that
        # came through intake, so this only fires if the template changed since.
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

        # ASSUMPTION: the renderer takes a TemplateVariant. Its old signature took
        # the single-channel Template, so TemplateRenderer needs the same update.
        return self._renderer.render(variant, notification.template_variables)
