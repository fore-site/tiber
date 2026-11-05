"""Install PostgreSQL extensions required by Tiber.

Revision ID: 2d9adfec7c5d
Revises:
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "2d9adfec7c5d"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install PostgreSQL extensions required by Tiber."""
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext";')


def downgrade() -> None:
    """Leave shared PostgreSQL extensions installed."""
