"""Allow external-ID-only recipients and index recipient feed reads.

Revision ID: 20261117_02
Revises: 20261117_01
Create Date: 2026-11-17 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261117_02"
down_revision: str | Sequence[str] | None = "20261117_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow recipients with an external ID and no channel addresses."""
    op.drop_constraint(
        "recipients_addresses_not_empty",
        "recipients",
        type_="check",
    )
    op.create_check_constraint(
        "recipients_identity_or_addresses",
        "recipients",
        "external_id IS NOT NULL OR addresses != '{}'::jsonb",
    )
    op.create_index(
        "ix_notifications_project_recipient_channel_created",
        "notifications",
        ["project_id", "recipient_id", "channel", "created_at"],
    )


def downgrade() -> None:
    """Restore the address requirement and drop the feed index."""
    op.drop_index(
        "ix_notifications_project_recipient_channel_created",
        table_name="notifications",
    )
    op.drop_constraint(
        "recipients_identity_or_addresses",
        "recipients",
        type_="check",
    )
    op.create_check_constraint(
        "recipients_addresses_not_empty",
        "recipients",
        "addresses != '{}'::jsonb",
    )
