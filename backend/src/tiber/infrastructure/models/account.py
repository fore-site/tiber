from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .types import AccountRoleType


class AccountModel(Base):
    """Dashboard accounts and their infrastructure-owned authentication state.

    The domain's Account entity remains an id-only ownership root; credential
    hashes, verification state, roles, and session-version state stay in this
    infrastructure model.
    """

    __tablename__ = "accounts"

    __table_args__ = (
        UniqueConstraint("email", name="accounts_email_unique"),
        UniqueConstraint("github_id", name="accounts_github_id_unique"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    email: Mapped[str] = mapped_column(
        CITEXT(),
        nullable=False,
    )

    password_hash: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Auth-layer role. Deliberately a plain string, not a domain enum: roles
    # are an auth concern and the domain does not model them.
    role: Mapped[str] = mapped_column(
        AccountRoleType,
        nullable=False,
        server_default="user",
    )

    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa.text("false"),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa.text("true"),
    )

    auth_version: Mapped[int] = mapped_column(
        nullable=False,
        server_default=sa.text("0"),
    )

    pending_email: Mapped[str | None] = mapped_column(
        CITEXT(),
        nullable=True,
    )

    github_id: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
