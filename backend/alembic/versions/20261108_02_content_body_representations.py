"""Support plain-text and HTML content representations.

Revision ID: 20261108_02
Revises: 20261108_01
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261108_02"
down_revision: str | None = "20261108_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow HTML-only variants and notifications."""
    op.alter_column("notifications", "body", nullable=True)
    op.alter_column("template_variants", "body", nullable=True)
    op.create_check_constraint(
        "notifications_content_body_check",
        "notifications",
        "(body IS NOT NULL AND btrim(body) <> '') OR "
        "(html_body IS NOT NULL AND btrim(html_body) <> '')",
    )
    op.create_check_constraint(
        "template_variants_content_body_check",
        "template_variants",
        "(body IS NOT NULL AND btrim(body) <> '') OR "
        "(html_body IS NOT NULL AND btrim(html_body) <> '')",
    )


def downgrade() -> None:
    """Restore plain-text-only database constraints."""
    op.drop_constraint(
        "template_variants_content_body_check",
        "template_variants",
        type_="check",
    )
    op.drop_constraint(
        "notifications_content_body_check",
        "notifications",
        type_="check",
    )
    op.alter_column("template_variants", "body", nullable=False)
    op.alter_column("notifications", "body", nullable=False)
