"""Template variable extraction (pure, no I/O).

A template declares its variables implicitly: every ``{{name}}`` placeholder in
its content is a variable the sender must supply. Nothing is declared separately,
so there is nothing to keep in sync.

IMPORTANT: ``VARIABLE_RE`` must recognise the same placeholders that
``TemplateRenderer`` substitutes. Reuse the renderer's pattern if it exposes
one. The regex below tolerates whitespace (``{{ name }}``), which is the safe
direction: if the renderer is stricter, an extra variable is demanded and
harmless; if it were looser, a variable would be missed and rendering would fail
after the request was accepted.

Likewise ``content_variables`` must cover exactly the fields the renderer
substitutes. If the renderer only touches title and body, drop the action and
image lines, or clients will be asked for variables that are never used.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..value_objects import NotificationContent

# Flat identifiers only: template_variables is a flat mapping of names to values.
VARIABLE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def extract_variables(text: str | None) -> frozenset[str]:
    """Names of the ``{{variable}}`` placeholders in one string."""
    if not text:
        return frozenset()
    return frozenset(VARIABLE_RE.findall(text))


def content_variables(content: NotificationContent) -> frozenset[str]:
    """Names of every placeholder in a piece of notification content."""
    found: set[str] = set()
    found |= extract_variables(content.title)
    found |= extract_variables(content.body)
    for action in content.actions:
        found |= extract_variables(action.label)
        found |= extract_variables(action.url)
    for image in content.images:
        found |= extract_variables(image.url)
        found |= extract_variables(image.alt)
    return frozenset(found)
