"""Pure template rendering for notification content.

Rendering is intentionally framework-free: given a ``Template`` and a flat
mapping of template variables, it substitutes ``{{variable}}`` placeholders
in the template content's title and body, returning a new
``NotificationContent``. It owns no I/O and no business rules beyond the
string substitution itself, so it lives in the domain layer and can be
tested in isolation.

Missing variables are substituted with the empty string rather than raising,
mirroring the "graceful degradation" principle used elsewhere in the pipeline.

"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ..value_objects import NotificationContent

if TYPE_CHECKING:
    from ..entities import Template

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


class TemplateRenderer:
    """Renders ``{{variable}}`` placeholders in a template's content."""

    def render(
        self, template: Template, variables: Mapping[str, Any] | None
    ) -> NotificationContent:
        """Render a template's content with the given variables.

        Every ``{{key}}`` placeholder is replaced with ``str(variables[key])``
        when the key is present, and with an empty string otherwise. The
        template's ``action_url`` / ``image_url`` pass through untouched.
        """
        mapping = variables or {}

        def _substitute(text: str) -> str:
            return _PLACEHOLDER_RE.sub(lambda m: str(mapping.get(m.group(1), "")), text)

        template_content = template.content
        title = _substitute(template_content.title) if template_content.title else None
        body = _substitute(template_content.body)
        return NotificationContent(
            title=title,
            body=body,
            action_url=template_content.action_url,
            image_url=template_content.image_url,
        )
