"""Helpers for extracting database constraint metadata from SQLAlchemy errors."""

from __future__ import annotations


def get_constraint_name(error: BaseException) -> str | None:
    """Find a constraint name on the SQLAlchemy or driver exception chain."""
    pending: list[BaseException] = [error]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))

        name = getattr(current, "constraint_name", None)
        if name:
            return name
        diagnostic = getattr(current, "diag", None)
        name = getattr(diagnostic, "constraint_name", None)
        if name:
            return name

        for nested in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return None
