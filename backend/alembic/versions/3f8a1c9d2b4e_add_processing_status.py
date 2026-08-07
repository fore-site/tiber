"""add processing to notification_status.

Mirrors docs/architecture/database/schema.sql. Adds the ``processing``
intermediate state (pending -> processing -> delivered/failed) used by the
worker while a notification is in flight, so a duplicate or concurrent
dispatch of the same id can no longer observe it as PENDING.

Revision ID: 3f8a1c9d2b4e
Revises: e5c9c18cafc1
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f8a1c9d2b4e"
down_revision: str | Sequence[str] | None = "e5c9c18cafc1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the 'processing' value to the notification_status enum."""
    # ADD VALUE IF NOT EXISTS is supported on PostgreSQL 12+ (and may be run
    # inside a transaction on those versions). The new value is appended at
    # the end of the enum ordering, which is fine since application code
    # compares by string value, not position.
    op.execute("ALTER TYPE notification_status ADD VALUE IF NOT EXISTS 'processing'")


def downgrade() -> None:
    """Remove the 'processing' value from the notification_status enum.

    PostgreSQL cannot drop an enum value in standard SQL, so on downgrade we
    only guard against a value that may not exist. If any notification rows
    currently hold 'processing' this operation is not safe; in practice this
    is a forward-only development guard.
    """
    # No-op downgrade: PostgreSQL does not support removing a single enum
    # value without recreating the type. Recreating the type would require a
    # full table rewrite and is intentionally out of scope for this migration.
    pass
