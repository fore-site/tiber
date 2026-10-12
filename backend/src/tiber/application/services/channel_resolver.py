"""Default channel resolution: one path for registered and address-based requests."""

from collections.abc import Sequence
from typing import Literal

from tiber.application.ports.channel_selection import ChannelSelection
from tiber.domain.entities import Recipient
from tiber.domain.enums import DeliveryChannel, NotificationCategory
from tiber.domain.exceptions import ChannelNotAvailableError

# How the channel set was chosen:
#   client    -> ``channels`` in the request (registered recipients only)
#   ranker    -> ML priority ranking
#   addresses -> addresses supplied in the request
ChannelSource = Literal["client", "ranker", "addresses"]


class ChannelResolver:
    """Resolves delivery channels.

    * Address-based request  -> exactly the channels the request supplied.
    * Client selection       -> that selection, which must be a subset of the
                                recipient's registered addresses.
    * Otherwise              -> the ML ranker, restricted to registered addresses.
    """

    def __init__(self, *, selector: ChannelSelection) -> None:
        """Initialize the channel resolver."""
        self._select = selector

    async def resolve(
        self,
        *,
        recipient: Recipient,
        requested: Sequence[DeliveryChannel] | None,
        category: NotificationCategory,
        adhoc_channels: frozenset[DeliveryChannel] | None,
    ) -> list[DeliveryChannel]:
        """Return the channels to deliver on.

        ``adhoc_channels`` is set only for address-based requests; it is the set
        of channels the request itself supplied, which may be smaller than what
        a matched recipient has accumulated over time.
        """
        # Address-based: the request defines the set, never the stored one.
        if adhoc_channels is not None:
            return sorted(adhoc_channels, key=lambda c: c.value)

        available = frozenset(recipient.addresses)

        if requested:
            missing = set(requested) - available
            if missing:
                raise ChannelNotAvailableError(
                    f"No registered address for: {sorted(ch.value for ch in missing)}"
                )
            # Deduplicate while preserving the client's order.
            return list(dict.fromkeys(requested))

        selected = [
            await self._select.select(
                recipient=recipient, available=available, category=category
            )
        ]
        if not selected:
            raise ChannelNotAvailableError(
                "No deliverable channel could be selected for this recipient."
            )
        return list(dict.fromkeys(selected))
