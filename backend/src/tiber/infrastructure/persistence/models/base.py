from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from tiber.core.config import get_settings

settings = get_settings()

# Engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # verify connection health before use
)

# Session factory
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Declarative base
class Base(DeclarativeBase):
    """
    All SQLAlchemy ORM models inherit from this base.
    Import in alembic/env.py for autogenerate support.
    """
    pass


# FastAPI dependency
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an AsyncSession per request, roll back on error, always close.
    Use as: db: AsyncSession = Depends(get_db)
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()