"""Pins for opaque cursor encoding and decoding.

Cursors are the contract between pages: they must round-trip exactly the
ordering fields the listing uses, and malformed input must fail loudly rather
than silently returning the first page again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tiber.application.pagination import (
    CursorPage,
    decode_cursor,
    decode_int_cursor,
    decode_time_id_cursor,
    encode_cursor,
)
from tiber.domain.exceptions import InvalidCursorError


def test_cursor_roundtrips_exact_fields():
    """A cursor decodes to the ordering key it was built from."""
    cursor = encode_cursor(attempt_number=7)

    assert decode_cursor(cursor, fields=("attempt_number",)) == {"attempt_number": "7"}


def test_cursor_rejects_another_listing():
    """A cursor from a different ordering cannot be replayed here."""
    cursor = encode_cursor(attempt_number=7)

    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor, fields=("occurred_at", "id"))


def test_malformed_cursor_is_rejected():
    """Garbage is a 422, not an accidental first page."""
    with pytest.raises(InvalidCursorError):
        decode_cursor("not-base64!!", fields=("id",))


def test_int_cursor_parses_and_rejects_zero():
    """Attempt numbers start at 1; zero cannot be a position."""
    assert (
        decode_int_cursor(encode_cursor(attempt_number=3), field="attempt_number") == 3
    )
    with pytest.raises(InvalidCursorError):
        decode_int_cursor(encode_cursor(attempt_number=0), field="attempt_number")


def test_time_id_cursor_roundtrips_utc():
    """Timestamp/id cursors keep both parts of the ordering key."""
    row_id = uuid4()
    timestamp = datetime(2026, 11, 12, 9, 14, tzinfo=UTC)
    cursor = encode_cursor(occurred_at=timestamp.isoformat(), id=row_id)

    assert decode_time_id_cursor(cursor, time_field="occurred_at") == (
        timestamp,
        row_id,
    )


def test_time_id_cursor_rejects_naive_timestamp():
    """A naive timestamp cannot be compared with stored timezone-aware rows."""
    cursor = encode_cursor(occurred_at="2026-11-12T09:14:00", id=uuid4())

    with pytest.raises(InvalidCursorError):
        decode_time_id_cursor(cursor, time_field="occurred_at")


def test_last_page_has_no_cursor():
    """The page type makes exhaustion explicit."""
    assert CursorPage(items=[1, 2]).next_cursor is None
