"""Add engagement event idempotency key.

Revision ID: 20261112_02
Revises: 20261112_01
Create Date: 2026-11-12 00:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261112_02"
down_revision: str | Sequence[str] | None = "20261112_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "engagement_events",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    # Partial, so provider-ingested rows (NULL) and legacy rows are unaffected.
    op.create_index(
        "uq_engagement_events_project_idempotency",
        "engagement_events",
        ["project_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_engagement_events_project_idempotency",
        table_name="engagement_events",
    )
    op.drop_column("engagement_events", "idempotency_key")
