"""Template resolution for notification content.

Resolves the final content of a notification at worker time: when the
notification references a template, the template is loaded through the
project-scoped lookup (ownership enforced by the repository contract), the
variant for the notification's channel is selected, and it is rendered with the
notification's variables.

Notifications carrying direct content (``template_id`` is None) are rendered
too: the content is Liquid source that may reference the variables supplied with
the request, and it obeys the same undefined, escaping and resource policies as
a saved template.
"""

from __future__ import annotations

from dataclasses import dataclass

from tiber.domain.entities import Notification, Template
from tiber.domain.exceptions import (
    EntityNotFoundError,
    TemplateChannelMismatchError,
)
from tiber.domain.repositories import TemplateRepository
from tiber.domain.services import TemplateRenderer
from tiber.domain.value_objects import NotificationContent


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
    ) -> None:
        """Initialize the resolver with its template repository."""
        self._templates = template_repository
        self._renderer = renderer or TemplateRenderer()

    async def resolve(self, notification: Notification) -> ResolvedTemplateContent:
        """Return rendered text and HTML for the notification's content."""
        if notification.template_id is None:
            return ResolvedTemplateContent(
                content=self._renderer.render_content(
                    notification.content,
                    notification.template_variables,
                )
            )

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

        return ResolvedTemplateContent(
            content=self._renderer.render(
                variant,
                notification.template_variables,
            ),
        )

    async def resolve_content(self, notification: Notification) -> NotificationContent:
        """Return only the rendered semantic content for compatibility."""
        return (await self.resolve(notification)).content
