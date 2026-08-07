"""Pure template rendering for notification content.

Rendering is intentionally framework-free: given a ``Template`` and a flat
mapping of template variables, it substitutes ``{{variable}}`` placeholders
in the template subject and body. It owns no I/O and no business rules beyond
the string substitution itself, so it lives in the domain layer and can be
tested in isolation.

Missing variables are substituted with the empty string rather than raising,
mirroring the "graceful degradation" principle used elsewhere in the pipeline.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..entities import Template

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


@dataclass(frozen=True)
class RenderedContent:
    """The result of rendering a template with a set of variables."""

    subject: str | None
    body: str


class TemplateRenderer:
    """Renders ``{{variable}}`` placeholders in a template's content."""

    def render(
        self, template: Template, variables: Mapping[str, Any] | None
    ) -> RenderedContent:
        """Render a template with the given variables.

        Every ``{{key}}`` placeholder is replaced with ``str(variables[key])``
        when the key is present, and with an empty string otherwise.
        """
        mapping = variables or {}

        def _substitute(text: str) -> str:
            return _PLACEHOLDER_RE.sub(lambda m: str(mapping.get(m.group(1), "")), text)

        subject = _substitute(template.subject) if template.subject else None
        body = _substitute(template.body)
        return RenderedContent(subject=subject, body=body)
