"""Unit tests for retry algebra: exponential backoff and attempt bounds."""

from __future__ import annotations

from tiber.worker.retry import exponential_backoff, is_retry_exhausted


def test_backoff_starts_at_base():
    """The first retry (attempt 0) waits exactly the base delay."""
    assert exponential_backoff(0, base_delay=30) == 30


def test_backoff_grows_geometrically():
    """Each retry doubles the wait, independent of other knobs."""
    base = 10
    assert exponential_backoff(0, base_delay=base) == 10
    assert exponential_backoff(1, base_delay=base) == 20
    assert exponential_backoff(2, base_delay=base) == 40
    assert exponential_backoff(3, base_delay=base) == 80


def test_backoff_respects_custom_factor():
    """Factor scales the growth schedule."""
    assert exponential_backoff(1, base_delay=10, factor=3) == 30
    assert exponential_backoff(2, base_delay=10, factor=3) == 90


def test_backoff_is_capped():
    """Backoff cannot grow beyond the configured maximum delay."""
    assert exponential_backoff(20, base_delay=30, max_delay=3600) == 3600


def test_backoff_clamps_negative_attempt():
    """A negative attempt index is never allowed to shrink the delay."""
    assert exponential_backoff(-5, base_delay=30) == 30


def test_is_retry_exhausted_boundary():
    """Attempts below the ceiling are not exhausted; at/above it they are."""
    assert not is_retry_exhausted(0, 4)
    assert not is_retry_exhausted(3, 4)
    assert is_retry_exhausted(4, 4)
    assert is_retry_exhausted(5, 4)
