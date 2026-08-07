"""create delivery_attempts table.

Mirrors docs/architecture/database/schema.sql. The delivery_channel and
delivery_attempt_status enum types already exist (created in
7249e18313e7), so only the table is created here.

Revision ID: e5c9c18cafc1
Revises: 7249e18313e7
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e5c9c18cafc1"
down_revision: str | Sequence[str] | None = "7249e18313e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the delivery_attempt_status enum and the delivery_attempts table."""
    # delivery_channel and delivery_attempt_status are both needed here;
    # delivery_channel is created by the core migration, delivery_attempt_status
    # is first used by this table (so it is created here).
    sa.Enum(
        "succeeded",
        "failed",
        name="delivery_attempt_status",
    ).create(op.get_bind(), checkfirst=True)

    op.create_table(
        "delivery_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "notification_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notifications.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.SmallInteger(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="delivery_attempt_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "channel",
            postgresql.ENUM(name="delivery_channel", create_type=False),
            nullable=False,
        ),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "notification_id",
            "attempt_number",
            name="delivery_attempts_notification_attempt_unique",
        ),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="delivery_attempts_attempt_number_check",
        ),
    )


def downgrade() -> None:
    """Drop the delivery_attempts table and its enum type."""
    op.drop_table("delivery_attempts")
    sa.Enum(name="delivery_attempt_status").drop(op.get_bind(), checkfirst=True)
