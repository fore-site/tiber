"""Persist recipient consent state (opt-outs and unsubscribes).

Revision ID: 20261117_03
Revises: 20261117_02
Create Date: 2026-11-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261117_03"
down_revision: str | Sequence[str] | None = "20261117_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store opt-outs and unsubscribes on the recipient."""
    op.add_column(
        "recipients",
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "recipients_preferences_type_check",
        "recipients",
        "jsonb_typeof(preferences) = 'object'",
    )


def downgrade() -> None:
    """Drop the recipient consent state."""
    op.drop_constraint(
        "recipients_preferences_type_check",
        "recipients",
        type_="check",
    )
    op.drop_column("recipients", "preferences")
