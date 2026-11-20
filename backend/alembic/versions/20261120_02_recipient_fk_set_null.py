"""Let a recipient be purged without deleting its delivery history.

Soft delete keeps the row for a grace period; the purge that follows removes it.
Delivery history must outlive that row, so ``notifications``,
``notification_intakes`` and ``engagement_events`` keep their own rows and lose
only the pointer: ``recipient_id`` becomes NULL.

``ON DELETE SET NULL`` is chosen over a dangling id because the erased row holds
nothing worth correlating, and because the foreign key keeps enforcing that any
*non-null* ``recipient_id`` still names a real recipient at write time.

Constraint names are PostgreSQL's defaults: the core schema declares these keys
unnamed, which yields ``<table>_recipient_id_fkey``.

Revision ID: 20261120_02
Revises: 20261120_01
Create Date: 2026-11-20 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261120_02"
down_revision: str | Sequence[str] | None = "20261120_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Each table holding a recipient pointer, and the index that keeps the parent
# delete from seq-scanning it. ``engagement_events`` is already indexed;
# ``notifications`` only has a composite index led by ``project_id``, which
# cannot serve a lookup on ``recipient_id`` alone, and ``notification_intakes``
# has no index on the column at all.
_TABLES: tuple[tuple[str, str | None], ...] = (
    ("notification_intakes", "ix_notification_intakes_recipient"),
    ("notifications", "ix_notifications_recipient"),
    ("engagement_events", None),
)


def _fk_name(table: str) -> str:
    """Return the name PostgreSQL gave the FK from ``table.recipient_id``."""
    return f"{table}_recipient_id_fkey"


def upgrade() -> None:
    """Make the recipient pointers nullable and null them on delete."""
    for table, index in _TABLES:
        name = _fk_name(table)
        op.drop_constraint(name, table, type_="foreignkey")
        # Must allow NULL before SET NULL: PostgreSQL accepts the clause on a
        # NOT NULL column and only fails later, at delete time.
        op.alter_column(table, "recipient_id", existing_type=sa.UUID(), nullable=True)
        op.create_foreign_key(
            name,
            table,
            "recipients",
            ["recipient_id"],
            ["id"],
            ondelete="SET NULL",
        )
        if index is not None:
            op.create_index(index, table, ["recipient_id"])


def downgrade() -> None:
    """Restore the restrictive foreign keys.

    Fails once a purge has actually nulled a pointer: those history rows have
    no recipient left to constrain against.
    """
    for table, index in _TABLES:
        if index is not None:
            op.drop_index(index, table_name=table)
        name = _fk_name(table)
        op.drop_constraint(name, table, type_="foreignkey")
        op.alter_column(table, "recipient_id", existing_type=sa.UUID(), nullable=False)
        op.create_foreign_key(
            name,
            table,
            "recipients",
            ["recipient_id"],
            ["id"],
            ondelete="RESTRICT",
        )
