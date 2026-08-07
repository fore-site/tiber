from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """All SQLAlchemy ORM models inherit from this base.

    Import in alembic/env.py for autogenerate support.
    """

    pass
