"""Add styled template bodies and reusable brand profiles.

Revision ID: 20261108_01
Revises: 20261105_01
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261108_01"
down_revision: str | None = "20261105_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create brand profiles and add HTML template content."""
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
    op.add_column("template_variants", sa.Column("html_body", sa.Text(), nullable=True))
    op.add_column("notifications", sa.Column("html_body", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove styled template content and brand profiles."""
    op.drop_column("notifications", "html_body")
    op.drop_column("template_variants", "html_body")
    op.drop_constraint(
        "templates_brand_profile_id_fkey", "templates", type_="foreignkey"
    )
    op.drop_column("templates", "brand_profile_id")
    op.drop_table("brand_profiles")
