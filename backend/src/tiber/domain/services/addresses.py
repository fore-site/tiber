"""Address normalization.

Matching ad-hoc recipients by address only works if stored and incoming values
are canonical, so every address passes through here before it is compared or
persisted.
"""

from collections.abc import Mapping

from tiber.domain.enums import DeliveryChannel


def normalize_address(channel: DeliveryChannel, value: str) -> str:
    """Return the canonical form of ``value`` for ``channel``."""
    value = value.strip()
    if channel is DeliveryChannel.EMAIL:
        return value.lower()
    # sms: E.164 is enforced by the request schema, so '+234803...' and
    #      '0803...' can never both reach this point.
    # push / in_app: opaque identifiers, kept verbatim.
    return value


def normalize_addresses(
    addresses: Mapping[DeliveryChannel, str],
) -> dict[DeliveryChannel, str]:
    """Normalize every address in a channel -> address mapping."""
    return {ch: normalize_address(ch, v) for ch, v in addresses.items()}
