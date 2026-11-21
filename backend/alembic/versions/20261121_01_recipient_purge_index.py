"""Index the tombstone scan used by the recipient purge.

The purge runs on a schedule and only ever looks at rows with ``deleted_at``
set, which are a small minority. A partial index keeps that lookup proportional
to the number of deleted recipients instead of the size of ``recipients``.

Revision ID: 20261121_01
Revises: 20261120_02
Create Date: 2026-11-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261121_01"
down_revision: str | Sequence[str] | None = "20261120_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_recipients_deleted_at"


def upgrade() -> None:
    """Add the partial tombstone index."""
    op.create_index(
        _INDEX,
        "recipients",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the partial tombstone index."""
    op.drop_index(_INDEX, table_name="recipients")
