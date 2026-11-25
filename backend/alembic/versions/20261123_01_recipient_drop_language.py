"""Drop the recipient ``language`` column.

Language was a profile fact intended for intelligent translation, but no
feature consumes it and the API never accepted it: every row was NULL in
practice. An unpopulated nullable column is not free - it reads as an
invitation to build against a fact nobody maintains, and it keeps a
BCP-47 validator in the domain that nothing can ever fail.

Dropping it is lossless in the deployed state (all NULL). The downgrade
recreates the column empty: any value written in the meantime is not
recoverable, because there is no source to restore it from.

Revision ID: 20261123_01
Revises: 20261121_01
Create Date: 2026-11-23 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261123_01"
down_revision: str | Sequence[str] | None = "20261121_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Matches the column the core schema created (20261101_01).
_LANGUAGE_LENGTH = 35


def upgrade() -> None:
    """Remove the unused profile fact."""
    op.drop_column("recipients", "language")


def downgrade() -> None:
    """Restore the column, empty: the dropped values cannot be recovered."""
    op.add_column(
        "recipients",
        sa.Column("language", sa.String(_LANGUAGE_LENGTH), nullable=True),
    )
