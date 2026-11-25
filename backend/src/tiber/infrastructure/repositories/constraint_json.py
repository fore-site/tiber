"""JSONB serialization for delivery-constraint value objects.

Project constraints and recipient preferences store the same two value objects.
Keeping their representations in one place means a stored window is read back
identically regardless of which aggregate owns it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time

from ...domain.enums import DeliveryChannel
from ...domain.value_objects import BlackoutPeriod, QuietHours


def blackout_to_json(period: BlackoutPeriod) -> dict[str, str]:
    """Serialize a blackout period to a JSONB document."""
    return {
        "name": period.name,
        "start": period.start.isoformat(),
        "end": period.end.isoformat(),
    }


def blackout_from_json(data: Mapping[str, object]) -> BlackoutPeriod:
    """Rehydrate a blackout period, letting the value object reject bad rows."""
    return BlackoutPeriod(
        name=str(data["name"]),
        start=datetime.fromisoformat(str(data["start"])),
        end=datetime.fromisoformat(str(data["end"])),
    )


def quiet_hours_to_json(window: QuietHours) -> dict[str, object]:
    """Serialize a quiet-hours window to a JSONB document."""
    return {
        "name": window.name,
        "window_start": window.window_start.isoformat(),
        "window_end": window.window_end.isoformat(),
        "channel": window.channel.value,
        "description": window.description,
    }


def quiet_hours_from_json(data: Mapping[str, object]) -> QuietHours:
    """Rehydrate a quiet-hours window, letting the value object reject bad rows."""
    description = data.get("description")
    return QuietHours(
        name=str(data["name"]),
        window_start=time.fromisoformat(str(data["window_start"])),
        window_end=time.fromisoformat(str(data["window_end"])),
        channel=DeliveryChannel(str(data["channel"])),
        description=description if isinstance(description, str) else None,
    )
