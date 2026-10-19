"""``{{variable}}`` placeholder extraction, shared by rendering and validation.

This lives in ``value_objects`` rather than ``domain.services`` on purpose:
``domain.services.__init__`` imports ``template_variant``, which imports the
services package back, so a module-level import of ``domain.services`` from
here would close an import cycle. The helper is pure text handling, so it has
no dependencies of its own.
"""

from __future__ import annotations

import re

# Matches the placeholder syntax the renderer substitutes. Kept here so the
# accept-time variable check and the renderer can never disagree about what a
# placeholder is.
TEMPLATE_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


def extract_placeholders(*texts: str | None) -> frozenset[str]:
    """Return every ``{{name}}`` referenced across ``texts``.

    ``None`` and empty strings contribute nothing. The result is a set because
    templates routinely repeat the same variable in the title and body.
    """
    return frozenset(
        name for text in texts if text for name in TEMPLATE_PLACEHOLDER_RE.findall(text)
    )
