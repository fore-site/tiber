"""Pure template rendering for notification content.

Rendering is intentionally framework-free: given a ``Template`` and a flat
mapping of template variables, it substitutes ``{{variable}}`` placeholders
in the template content's title and body representations, returning a new
``NotificationContent``.

Missing placeholders are an error, not empty text: see ``TemplateRenderer.render``.

"""

from __future__ import annotations

import html
import re
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

_BRAND_TOKEN_RE = re.compile(r"\[\[([a-z][a-z0-9-]{0,62})\]\]")


class TemplateRenderer:
    """Renders ``{{variable}}`` placeholders in a template's content."""

    def render(
        self,
        template: TemplateVariant,
        variables: Mapping[str, Any] | None,
        brand_tokens: Mapping[str, str] | None = None,
    ) -> NotificationContent:
        """Render a template's content with the given variables.

        Every ``{{key}}`` placeholder in title and body fields must have a non-None
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
                    template.content.title,
                    template.content.plain_text_body,
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
        plain_text_body = (
            _substitute(template_content.plain_text_body)
            if template_content.plain_text_body is not None
            else None
        )
        html_body = self.render_html(template, variables, brand_tokens)
        return NotificationContent(
            title=title,
            plain_text_body=plain_text_body,
            html_body=html_body,
            actions=template_content.actions,
            images=template_content.images,
        )

    def render_html(
        self,
        template: TemplateVariant,
        variables: Mapping[str, Any] | None,
        brand_tokens: Mapping[str, str] | None = None,
    ) -> str | None:
        """Render a variant's HTML with escaped variables and brand tokens."""
        template_html = template.content.html_body
        if template_html is None:
            return None

        mapping = variables or {}
        tokens = brand_tokens or {}
        missing_variables = {
            name
            for name in extract_placeholders(template_html)
            if mapping.get(name) is None
        }
        missing_tokens = set(_BRAND_TOKEN_RE.findall(template_html)) - set(tokens)
        if missing_variables or missing_tokens:
            raise TemplateRenderError(
                tuple(
                    sorted(
                        [f"variable:{name}" for name in missing_variables]
                        + [f"brand:{name}" for name in missing_tokens]
                    )
                )
            )

        rendered = TEMPLATE_PLACEHOLDER_RE.sub(
            lambda match: html.escape(str(mapping[match.group(1)]), quote=True),
            template_html,
        )
        rendered = _BRAND_TOKEN_RE.sub(
            lambda match: html.escape(tokens[match.group(1)], quote=True),
            rendered,
        )
        if tokens:
            declarations = ";".join(
                f"--tiber-{key}:{value}" for key, value in sorted(tokens.items())
            )
            style = f"<style>:root{{{declarations}}}</style>"
            head = re.search(r"<head(?:\s[^>]*)?>", rendered, re.IGNORECASE)
            if head:
                rendered = rendered[: head.end()] + style + rendered[head.end() :]
            else:
                rendered = style + rendered
        return rendered
