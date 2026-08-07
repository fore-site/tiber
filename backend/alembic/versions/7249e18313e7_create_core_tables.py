"""create_core_tables.

Creates the PostgreSQL enum types and the core tables required by the
current model layer: users, projects, templates, recipients, notifications.

Column-for-column faithful to docs/architecture/database/schema.sql so the
migration and the design doc stay in lockstep.

Revision ID: 7249e18313e7
Revises: 2d9adfec7c5d
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7249e18313e7"
down_revision: str | Sequence[str] | None = "2d9adfec7c5d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum types used by the core tables. The SQLAlchemy model layer declares
# these with create_type=False (see infrastructure/models/types.py) and
# relies on migrations to create them, so we create them explicitly here
# (via raw SQL) before any table that references them.
_ENUMS: dict[str, tuple[str, ...]] = {
    "delivery_channel": ("email", "push", "sms", "webhook", "in_app"),
    "user_role": ("admin", "user"),
    "notification_status": (
        "pending",
        "policy_rejected",
        "cancelled",
        "delivered",
        "failed",
    ),
    "send_time_basis": ("explicit", "ml_predicted", "immediate"),
}


def _create_enums() -> None:
    """Create the PG enum types used by the core tables (idempotent)."""
    for name, labels in _ENUMS.items():
        quoted = ", ".join(f"'{label}'" for label in labels)
        op.execute(f"CREATE TYPE {name} AS ENUM ({quoted});")


def _drop_enums() -> None:
    """Drop the PG enum types created in _create_enums (reverse order)."""
    for name in reversed(list(_ENUMS)):
        op.execute(f"DROP TYPE IF EXISTS {name};")


def upgrade() -> None:
    """Create the enum types and the core tables."""
    _create_enums()

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column(
            "role",
            postgresql.ENUM(name="user_role", create_type=False),
            nullable=False,
            server_default="user",
        ),
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("pending_email", postgresql.CITEXT(), nullable=True),
        sa.Column("github_id", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("email", name="users_email_unique"),
        sa.UniqueConstraint("github_id", name="users_github_id_unique"),
    )

    op.create_table(
        "projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "slug", name="projects_user_slug_unique"),
    )

    op.create_table(
        "templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column(
            "channel",
            postgresql.ENUM(name="delivery_channel", create_type=False),
            nullable=False,
        ),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("project_id", "slug", name="templates_project_slug_unique"),
        sa.UniqueConstraint("project_id", "name", name="templates_name_unique"),
        sa.CheckConstraint(
            "(channel = 'email' AND subject IS NOT NULL) "
            "OR (channel <> 'email' AND subject IS NULL)",
            name="templates_subject_check",
        ),
    )

    op.create_table(
        "recipients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("addresses", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "project_id",
            "external_id",
            name="recipients_project_external_id_unique",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(addresses) = 'object'",
            name="recipients_address_type_check",
        ),
        sa.CheckConstraint(
            "addresses != '{}'::jsonb",
            name="recipients_addresses_not_empty",
        ),
    )

    op.create_table(
        "notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "recipient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recipients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "channel",
            postgresql.ENUM(name="delivery_channel", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="notification_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column(
            "correlation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("template_variables", postgresql.JSONB(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "send_time_basis",
            postgresql.ENUM(name="send_time_basis", create_type=False),
            nullable=False,
            server_default="immediate",
        ),
        sa.Column("policy_violation_reason", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "project_id",
            "idempotency_key",
            name="notifications_project_idempotency_key_unique",
        ),
        sa.CheckConstraint(
            "template_variables IS NULL OR jsonb_typeof(template_variables) = 'object'",
            name="notifications_template_variables_check",
        ),
        sa.CheckConstraint(
            "(status = 'policy_rejected' AND policy_violation_reason IS NOT NULL) "
            "OR (status <> 'policy_rejected' AND policy_violation_reason IS NULL)",
            name="notifications_policy_violation_check",
        ),
        sa.CheckConstraint(
            "(channel = 'email' AND subject IS NOT NULL) "
            "OR (channel <> 'email' AND subject IS NULL)",
            name="notifications_subject_check",
        ),
    )


def downgrade() -> None:
    """Drop the core tables and their enum types (reverse order)."""
    op.drop_table("notifications")
    op.drop_table("recipients")
    op.drop_table("templates")
    op.drop_table("projects")
    op.drop_table("users")
    _drop_enums()
