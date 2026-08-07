"""Template resolution for notification content.

Resolves the final content of a notification at worker time: when the
notification references a template, the template is loaded, ownership and
channel are validated, and it is rendered with the notification's variables.
Notifications carrying direct content (``template_id`` is None) pass through
unchanged — the "direct content fallback" path.
"""

from __future__ import annotations

from tiber.domain.entities import Notification
from tiber.domain.exceptions import (
    ProjectScopeViolationError,
    TemplateChannelMismatchError,
    TemplateNotFoundError,
)
from tiber.domain.repositories.template_repository import TemplateRepository
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

        template = await self._templates.get_by_id(notification.template_id)
        if template is None:
            raise TemplateNotFoundError(str(notification.template_id))

        if template.project_id != notification.project_id:
            raise ProjectScopeViolationError(
                str(notification.project_id),
                "template does not belong to the notification's project",
            )

        if template.channel != notification.channel:
            raise TemplateChannelMismatchError(
                str(notification.template_id),
                str(template.channel.value),
                str(notification.channel.value),
            )

        rendered = self._renderer.render(template, notification.template_variables)
        return NotificationContent(
            subject=rendered.subject,
            body=rendered.body,
        )
