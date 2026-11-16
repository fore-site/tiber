"""Remove retired brand profiles.

Revision ID: 20261116_01
Revises: 20261112_02
Create Date: 2026-11-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261116_01"
down_revision: str | Sequence[str] | None = "20261112_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the brand-profile table and its template reference."""
    op.drop_constraint(
        "templates_brand_profile_id_fkey", "templates", type_="foreignkey"
    )
    op.drop_column("templates", "brand_profile_id")
    op.drop_table("brand_profiles")


def downgrade() -> None:
    """Recreate the brand-profile table and its template reference."""
    op.create_table(
        "brand_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("tokens", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "name",
            name="brand_profiles_project_name_unique",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(tokens) = 'object'",
            name="brand_profiles_tokens_object_check",
        ),
    )
    op.add_column(
        "templates",
        sa.Column("brand_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "templates_brand_profile_id_fkey",
        "templates",
        "brand_profiles",
        ["brand_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
