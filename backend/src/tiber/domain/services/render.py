"""Pure template rendering with Liquid.

Rendering is intentionally framework-free: given a ``TemplateVariant`` and a
flat mapping of template variables, it renders the title, plain text body and
HTML body through one Liquid environment.

Policy
------
* Undefined variables are ``FalsyStrictUndefined``: absent names are falsy in
  ``{% if %}`` and resolvable with ``| default``, but *printing* one raises
  ``TemplateRenderError`` instead of silently leaving a hole in the message.
* Autoescaping is OFF, matching LiquidJS. Content is authored by the client, not
  by end users; a template that interpolates untrusted values must apply
  ``| escape`` itself. This also lets ``{{ body }}`` inject HTML fragments,
  which is the point of authoring HTML.
* Rendering is bounded (``_RENDER_LIMITS``): a client-authored template cannot
  exhaust a worker with a huge loop or a runaway output.
* There is no template loader, so ``{% include %}`` and ``{% render %}`` fail
  instead of reading files from the host.

Direct notification content (``template_id`` is None) is rendered here too: a
send may carry Liquid source without a saved template, and the same policies
(undefined handling, escaping, resource bounds) must apply to it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from liquid import Environment, FalsyStrictUndefined, ResourceLimits
from liquid.exceptions import LiquidError

from ..exceptions import TemplateRenderError

# Import the concrete module, not the package: ``value_objects/__init__`` imports
# ``TemplateVariant``, which imports this package, so reaching for the package
# here closes an import cycle that breaks every ``tiber.domain.entities`` import.
from ..value_objects.notification_content import NotificationContent

if TYPE_CHECKING:
    from ..value_objects.template_variant import TemplateVariant

# Bounds applied to every render. ``max_render_size`` matches the API's
# html_body limit, so a template cannot produce more than it could have carried
# as source. The rest stop runaway loops and pathological nesting.
_RENDER_LIMITS = ResourceLimits(
    max_render_size=1_000_000,
    max_loop_iterations=10_000,
    max_context_depth=20,
    max_block_depth=20,
    max_expression_depth=50,
)


class TemplateRenderer:
    """Render a template's content with Liquid."""

    def __init__(self, environment: Environment | None = None) -> None:
        """Initialize the renderer with a bounded, strict-output environment.

        ``environment`` exists so tests (or a future engine swap) can inject
        one; production always uses the bounded environment built here.
        """
        self._environment = environment or Environment(
            undefined=FalsyStrictUndefined,
            autoescape=False,
            resource_limits=_RENDER_LIMITS,
        )

    def render(
        self,
        template: TemplateVariant,
        variables: Mapping[str, Any] | None,
    ) -> NotificationContent:
        """Render a template variant's content with ``variables``."""
        return self.render_content(template.content, variables)

    def render_content(
        self,
        content: NotificationContent,
        variables: Mapping[str, Any] | None,
    ) -> NotificationContent:
        """Render one piece of notification content with ``variables``.

        Shared by saved templates and direct content: a send without a template
        still carries Liquid source, and it must be rendered under the same
        policies.

        A placeholder with no value raises ``TemplateRenderError`` rather than
        rendering as empty text: the usual cause is that the content was edited
        after the request was accepted, and a message with a silent hole in it
        is worse than a failed intake.

        ``actions`` / ``images`` pass through untouched: they are opaque
        references (labels + URLs), not free text to interpolate.
        """
        mapping = variables or {}

        title = self._render_text(content.title, mapping, field="title")
        plain_text_body = self._render_text(
            content.plain_text_body, mapping, field="plain_text_body"
        )
        html_body = self._render_text(content.html_body, mapping, field="html_body")

        try:
            return NotificationContent(
                title=title,
                plain_text_body=plain_text_body,
                html_body=html_body,
                actions=content.actions,
                images=content.images,
            )
        except ValueError as exc:
            # Liquid can render a body into nothing (e.g. a false conditional),
            # leaving content that the value object rejects.
            raise TemplateRenderError(
                (),
                reason=f"Rendered content is not valid: {exc}",
            ) from exc

    def _render_text(
        self, source: str | None, variables: Mapping[str, Any], *, field: str
    ) -> str | None:
        """Render one field, leaving a ``None`` field unset."""
        if source is None:
            return None
        return self._render(source, variables, field=field)

    def _render(self, source: str, variables: Mapping[str, Any], *, field: str) -> str:
        """Render one field, translating Liquid failures into a domain error."""
        try:
            return self._environment.render(source, variables)
        except LiquidError as exc:
            # Liquid errors carry a multi-line source excerpt; the first line
            # is the part worth showing an author or logging.
            reason = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            raise TemplateRenderError((), reason=f"{field}: {reason}") from exc
