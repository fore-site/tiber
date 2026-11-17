"""Add project sender identities.

Revision ID: 20261117_01
Revises: 20261116_01
Create Date: 2026-11-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261117_01"
down_revision: str | Sequence[str] | None = "20261116_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the project sender identity table."""
    op.create_table(
        "sender_identities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "channel",
            postgresql.ENUM(
                "email",
                "push",
                "sms",
                "in_app",
                name="delivery_channel",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("from_email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("reply_to", sa.String(length=320), nullable=True),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("provider_domain_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "dns_records",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "channel",
            name="sender_identities_project_channel_unique",
        ),
        sa.UniqueConstraint(
            "provider",
            "domain",
            name="sender_identities_provider_domain_unique",
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_domain_id",
            name="sender_identities_provider_domain_id_unique",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(dns_records) = 'array'",
            name="sender_identities_dns_records_check",
        ),
    )
    op.create_index(
        "ix_sender_identities_project",
        "sender_identities",
        ["project_id"],
    )


def downgrade() -> None:
    """Drop the project sender identity table."""
    op.drop_index("ix_sender_identities_project", table_name="sender_identities")
    op.drop_table("sender_identities")
