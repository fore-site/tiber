"""Allow a deleted recipient to be an identity-less tombstone.

Soft delete scrubs the personal data immediately, so a deleted row has neither
an external id nor addresses. The identity constraint therefore describes live
rows only; ``deleted_at`` (created with the core schema) marks the tombstone.

Revision ID: 20261120_01
Revises: 20261117_03
Create Date: 2026-11-20 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261120_01"
down_revision: str | Sequence[str] | None = "20261117_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "recipients_identity_or_addresses"
_LIVE_ONLY = "external_id IS NOT NULL OR addresses != '{}'::jsonb"
_ALLOW_DELETED = f"{_LIVE_ONLY} OR deleted_at IS NOT NULL"


def upgrade() -> None:
    """Let a deleted row hold no identity and no addresses."""
    op.drop_constraint(_CONSTRAINT, "recipients", type_="check")
    op.create_check_constraint(_CONSTRAINT, "recipients", _ALLOW_DELETED)


def downgrade() -> None:
    """Restore the live-only identity constraint.

    Fails while scrubbed tombstones exist: they have no identity or addresses
    to satisfy the restored constraint, so purge them first.
    """
    op.drop_constraint(_CONSTRAINT, "recipients", type_="check")
    op.create_check_constraint(_CONSTRAINT, "recipients", _LIVE_ONLY)
