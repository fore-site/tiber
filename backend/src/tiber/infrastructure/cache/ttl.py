from __future__ import annotations

from datetime import timedelta


class RedisTTL:
    """Centralised TTL definitions for Redis keys.

    All durations are expressed as ``timedelta`` objects instead of raw
    integers to improve readability and avoid unit conversion mistakes.

    Dynamic TTLs (e.g. JWT blocklist entries) are computed by the owning
    store rather than defined here.
    """

    def __new__(cls):
        """Class is non-instantiable."""
        raise TypeError("RedisTTL cannot be instantiated.")

    #: Additional time added to JWT expiry when revoking tokens.
    #: Helps tolerate minor clock skew between clients and servers.
    CLOCK_SKEW = timedelta(seconds=30)

    #: Idempotency entries remain valid for 24 hours, matching the API contract.
    IDEMPOTENCY = timedelta(hours=24)

    #: Distributed lock duration.
    #: Prevents abandoned locks while giving workers enough time to complete.
    DISTRIBUTED_LOCK = timedelta(seconds=60)

    #: Prediction cache lifetime (reserved for future ML optimisation).
    PREDICTION_CACHE = timedelta(hours=6)

    API_KEY_CACHE = timedelta(hours=24)
