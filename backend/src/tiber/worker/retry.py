"""Pure helpers for Celery delivery retries (exponential backoff and bounds).

Kept free of Celery/Redis/DB dependencies so the retry algebra is directly
unit-testable in isolation.
"""

from __future__ import annotations


def exponential_backoff(
    attempt: int,
    *,
    base_delay: int = 30,
    factor: int = 2,
    max_delay: int = 3600,
) -> int:
    """Seconds to wait before the next delivery attempt.

    ``attempt`` is the number of prior attempts (0 for the very first retry), so
    the first retry waits ``base_delay`` seconds and the wait grows
    geometrically (``base_delay * factor ** attempt``), capped at ``max_delay``
    so backoff cannot grow unbounded.
    """
    clamped_attempt = max(0, attempt)
    delay = base_delay * (factor**clamped_attempt)
    return min(max_delay, delay)


def is_retry_exhausted(attempt: int, max_attempts: int) -> bool:
    """Return True once ``attempt`` has reached the configured ceiling."""
    return attempt >= max(1, max_attempts)
