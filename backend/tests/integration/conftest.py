from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

DATABASE_ENV = "TIBER_INTEGRATION_DATABASE_URL"
REDIS_ENV = "TIBER_INTEGRATION_REDIS_URL"


@pytest.fixture
async def integration_engine() -> AsyncIterator[AsyncEngine]:
    """Create isolated PostgreSQL objects in a temporary schema."""
    database_url = os.getenv(DATABASE_ENV)
    if not database_url:
        pytest.skip(f"integration: set {DATABASE_ENV} to a disposable database")

    from tiber.infrastructure.models import types as model_types
    from tiber.infrastructure.models.base import Base

    schema = f"tiber_test_{uuid4().hex}"
    admin_engine = create_async_engine(database_url, poolclass=NullPool)
    engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )
    schema_created = False

    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        schema_created = True

        enum_types = [
            value
            for value in vars(model_types).values()
            if isinstance(value, postgresql.ENUM)
        ]
        async with engine.begin() as connection:
            for enum in enum_types:
                await connection.run_sync(
                    lambda sync_connection, enum_type=enum: enum_type.create(
                        sync_connection, checkfirst=True
                    )
                )
            await connection.run_sync(Base.metadata.create_all)

        yield engine
    finally:
        await engine.dispose()
        if schema_created:
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin_engine.dispose()


@pytest.fixture
async def integration_session(
    integration_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    """Provide one database session for a test."""
    factory = async_sessionmaker(integration_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def integration_redis() -> AsyncIterator[Redis]:
    """Connect to the configured Redis integration service."""
    redis_url = os.getenv(REDIS_ENV)
    if not redis_url:
        pytest.skip(f"integration: set {REDIS_ENV} to a disposable Redis instance")

    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        await client.ping()
        yield client
    finally:
        await client.aclose()
