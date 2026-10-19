"""Pure template rendering for notification content.

Rendering is intentionally framework-free: given a ``Template`` and a flat
mapping of template variables, it substitutes ``{{variable}}`` placeholders
in the template content's title and body, returning a new
``NotificationContent``.

Missing placeholders are an error, not empty text: see ``TemplateRenderer.render``.

"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ..exceptions import TemplateRenderError

# Import the concrete module, not the package: ``value_objects/__init__`` imports
# ``TemplateVariant``, which imports this package, so reaching for the package
# here closes an import cycle that breaks every ``tiber.domain.entities`` import.
from ..value_objects.notification_content import NotificationContent
from ..value_objects.placeholders import TEMPLATE_PLACEHOLDER_RE, extract_placeholders

if TYPE_CHECKING:
    from ..value_objects.template_variant import TemplateVariant


class TemplateRenderer:
    """Renders ``{{variable}}`` placeholders in a template's content."""

    def render(
        self, template: TemplateVariant, variables: Mapping[str, Any] | None
    ) -> NotificationContent:
        """Render a template's content with the given variables.

        Every ``{{key}}`` placeholder in the title and body must have a non-None
        value in ``variables``. A placeholder with no value raises
        ``TemplateRenderError`` rather than rendering as empty text: the usual
        cause is that the template was edited after the request was accepted,
        and a message with a silent hole in it is worse than a failed intake.

        The template's ``actions`` / ``images`` pass through untouched: they are
        opaque references (labels + URLs), not free text to interpolate.
        """
        mapping = variables or {}

        missing = tuple(
            sorted(
                name
                for name in extract_placeholders(
                    template.content.title, template.content.body
                )
                if mapping.get(name) is None
            )
        )
        if missing:
            raise TemplateRenderError(missing)

        def _substitute(text: str) -> str:
            return TEMPLATE_PLACEHOLDER_RE.sub(lambda m: str(mapping[m.group(1)]), text)

        template_content = template.content
        title = _substitute(template_content.title) if template_content.title else None
        body = _substitute(template_content.body)
        return NotificationContent(
            title=title,
            body=body,
            actions=template_content.actions,
            images=template_content.images,
        )
