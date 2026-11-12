"""Add engagement events and webhook endpoints.

Revision ID: 20261112_01
Revises: 20261101_01
Create Date: 2026-11-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261112_01"
down_revision: str | Sequence[str] | None = "20261108_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # ``delivery_channel`` already exists from the core schema; referencing it
    # with create_type=False only borrows the type.
    delivery_channel = postgresql.ENUM(
        "email",
        "push",
        "sms",
        "in_app",
        name="delivery_channel",
        create_type=False,
    )

    op.create_table(
        "engagement_events",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("notification_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("recipient_id", sa.UUID(), nullable=False),
        sa.Column(
            "event_type",
            postgresql.ENUM(
                "open",
                "click",
                "bounce",
                "complaint",
                "unsubscribe",
                name="engagement_event_type",
            ),
            nullable=False,
        ),
        sa.Column("channel", delivery_channel, nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "is_synthetic",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "metadata IS NULL OR jsonb_typeof(metadata) = 'object'",
            name="engagement_events_metadata_check",
        ),
        sa.ForeignKeyConstraint(
            ["notification_id"], ["notifications.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["recipient_id"], ["recipients.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_engagement_events_project_occurred",
        "engagement_events",
        ["project_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_engagement_events_notification",
        "engagement_events",
        ["notification_id"],
        unique=False,
    )
    op.create_index(
        "ix_engagement_events_recipient",
        "engagement_events",
        ["recipient_id"],
        unique=False,
    )

    op.create_table(
        "webhook_endpoints",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "events",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("encrypted_signing_secret", sa.Text(), nullable=False),
        sa.Column("secret_prefix", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(events) = 'array'",
            name="webhook_endpoints_events_check",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_webhook_endpoints_project",
        "webhook_endpoints",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_webhook_endpoints_project", table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")
    op.drop_index("ix_engagement_events_recipient", table_name="engagement_events")
    op.drop_index("ix_engagement_events_notification", table_name="engagement_events")
    op.drop_index(
        "ix_engagement_events_project_occurred", table_name="engagement_events"
    )
    op.drop_table("engagement_events")
    op.execute("DROP TYPE IF EXISTS webhook_event_type")
    op.execute("DROP TYPE IF EXISTS engagement_event_type")
