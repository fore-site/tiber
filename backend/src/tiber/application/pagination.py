"""Opaque keyset-pagination cursors.

A cursor carries the ordering key of the last row a client saw. The next page
is selected with ``WHERE (ordering key...) < cursor`` rather than ``OFFSET``,
so rows inserted or deleted between pages cannot shift the window.

Cursors are base64url-encoded JSON, not encrypted or signed: they contain no
secrets, and tampering with one only changes which page the client reads.
Malformed cursors are rejected with ``InvalidCursorError`` (HTTP 422).
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from tiber.domain.exceptions import InvalidCursorError


@dataclass(frozen=True)
class CursorPage[T]:
    """One page plus the cursor for the next page (None on the last page)."""

    items: list[T]
    next_cursor: str | None = None


def encode_cursor(**values: Any) -> str:
    """Encode an ordering key as an opaque, URL-safe cursor."""
    payload = {key: str(value) for key, value in values.items()}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, *, fields: tuple[str, ...]) -> dict[str, str]:
    """Decode a cursor, requiring exactly the fields the caller ordered by."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, binascii.Error) as exc:
        raise InvalidCursorError("Cursor is not valid.") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != set(fields)
        or not all(isinstance(value, str) and value for value in payload.values())
    ):
        raise InvalidCursorError("Cursor does not match this listing.")
    return payload


def decode_int_cursor(cursor: str | None, *, field: str) -> int | None:
    """Decode an integer ordering key, e.g. ``attempt_number``."""
    if cursor is None:
        return None
    payload = decode_cursor(cursor, fields=(field,))
    try:
        value = int(payload[field])
    except ValueError as exc:
        raise InvalidCursorError("Cursor is not valid.") from exc
    if value < 1:
        raise InvalidCursorError("Cursor is not valid.")
    return value


def decode_time_id_cursor(
    cursor: str | None, *, time_field: str
) -> tuple[datetime, UUID] | None:
    """Decode a ``(timestamp, id)`` ordering key used by newest-first lists."""
    if cursor is None:
        return None
    payload = decode_cursor(cursor, fields=(time_field, "id"))
    try:
        timestamp = datetime.fromisoformat(payload[time_field])
        row_id = UUID(payload["id"])
    except ValueError as exc:
        raise InvalidCursorError("Cursor is not valid.") from exc
    if timestamp.tzinfo is None:
        raise InvalidCursorError("Cursor is not valid.")
    return timestamp, row_id
