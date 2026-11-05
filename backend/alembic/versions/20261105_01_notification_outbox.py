"""Create the transactional notification outbox.

Revision ID: 20261105_01
Revises: 20261102_01
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261105_01"
down_revision: str | None = "20261102_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the durable outbox and its due-message index."""
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "priority",
            sa.SmallInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('intake', 'dispatch')",
            name="outbox_kind_check",
        ),
        sa.CheckConstraint("priority IN (0, 1)", name="outbox_priority_check"),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="outbox_payload_check",
        ),
        sa.PrimaryKeyConstraint("id", name="outbox_pkey"),
    )
    op.create_index(
        "ix_outbox_unpublished",
        "outbox",
        ["priority", "available_at", "id"],
        unique=False,
        postgresql_where=sa.text("published_at IS NULL AND dead_lettered_at IS NULL"),
    )
    op.create_index(
        "ix_outbox_aggregate",
        "outbox",
        ["aggregate_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the transactional outbox."""
    op.drop_index("ix_outbox_aggregate", table_name="outbox")
    op.drop_index("ix_outbox_unpublished", table_name="outbox")
    op.drop_table("outbox")
