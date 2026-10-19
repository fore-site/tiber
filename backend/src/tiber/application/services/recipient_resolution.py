"""Recipient resolution, extracted so intake (sync) owns it in one place.

Registered recipient: looked up by external id.
Address-based request: matched to an existing recipient by address, or created
and persisted, so later requests to the same addresses reuse it.

Rules for address-based requests
    zero matches                        -> create and persist
    one match                           -> reuse; append channels it lacks
    several matches                     -> AmbiguousRecipientError (409)
    different address on a known channel -> AddressConflictError (409)

Once this lives here, delete ``_resolve_recipient``, ``_resolve_adhoc`` and
``_extend`` from the old ``NotificationService``.
"""

from collections.abc import Mapping
from uuid import UUID

from tiber.domain.entities import Recipient
from tiber.domain.enums import DeliveryChannel
from tiber.domain.exceptions import (
    AddressConflictError,
    AmbiguousRecipientError,
    EntityNotFoundError,
    RecipientAddressTakenError,
)
from tiber.domain.repositories import RecipientRepository
from tiber.domain.services.addresses import normalize_addresses


class RecipientResolutionService:
    """Resolve a registered recipient or match/create an address-based one."""

    def __init__(self, *, recipient_repository: RecipientRepository) -> None:
        """Initialize the service with the recipient repository."""
        self._recipients = recipient_repository

    async def resolve(
        self,
        *,
        project_id: UUID,
        recipient_id: str | None,
        addresses: Mapping[DeliveryChannel, str],
    ) -> Recipient:
        """Resolve the request's recipient, creating one when needed."""
        if recipient_id is not None:
            if addresses:
                raise ValueError("Provide either `recipient_id` or addresses, not both")
            recipient = await self._recipients.get_by_external_id(
                recipient_id, project_id
            )
            if recipient is None:
                raise EntityNotFoundError(Recipient, recipient_id)
            return recipient
        return await self._resolve_adhoc(project_id, addresses)

    async def _resolve_adhoc(
        self, project_id: UUID, addresses: Mapping[DeliveryChannel, str]
    ) -> Recipient:
        if not addresses:
            raise ValueError("Address-based requests need at least one address")
        normalized = normalize_addresses(addresses)

        for _ in range(2):  # second pass only after losing a creation race
            matches = {
                r.id: r
                for r in await self._recipients.find_by_addresses(
                    project_id, normalized
                )
            }

            if len(matches) > 1:
                raise AmbiguousRecipientError(
                    "Supplied addresses belong to different recipients. "
                    "Send them in separate requests or register a recipient."
                )

            if not matches:
                try:
                    return await self._recipients.add(
                        Recipient.create(project_id=project_id, addresses=normalized)
                    )
                except RecipientAddressTakenError:
                    continue  # someone created it first; re-read

            return await self._extend(next(iter(matches.values())), normalized)

        raise AmbiguousRecipientError("Could not resolve recipient; retry the request.")

    async def _extend(
        self, existing: Recipient, supplied: Mapping[DeliveryChannel, str]
    ) -> Recipient:
        conflicts = sorted(
            ch.value
            for ch, addr in supplied.items()
            if ch in existing.addresses and existing.addresses[ch] != addr
        )
        if conflicts:
            raise AddressConflictError(
                f"Recipient already has a different address for: {conflicts}"
            )

        new = {ch: a for ch, a in supplied.items() if ch not in existing.addresses}
        if not new:
            return existing

        # update_addresses replaces the whole book, so pass a fresh merged dict.
        updated = existing.update_addresses({**existing.addresses, **new})
        try:
            await self._recipients.save(updated)
        except RecipientAddressTakenError as exc:  # claimed concurrently elsewhere
            raise AmbiguousRecipientError(
                "A supplied address belongs to another recipient."
            ) from exc
        return updated
