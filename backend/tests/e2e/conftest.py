"""Harness for end-to-end tests: the real ASGI app against a real Postgres.

Enable with a dedicated database (never the development one, because the
harness creates and drops tables):

    docker compose up -d postgres
    createdb -U postgres tiber_e2e
    TIBER_TEST_DATABASE_URL=postgresql+asyncpg://postgres:tiber@localhost:5432/tiber_e2e \
        uv run pytest tests/e2e -q

Two deliberate stand-ins, both documented where they are installed below:

* Authentication is overridden with the fixture's project. ``get_authenticated_project``
  only checks that a Bearer header exists (Phase 7 work), so testing it here would
  pin a stub, not a contract.
* Ingestion rate limiting is overridden with an allow-all limiter so a Redis
  instance is not required. The 429 journey swaps in a deny-all limiter instead.

Schema is created from ``Base.metadata`` because the project has no Alembic
baseline yet. When migrations exist, replace ``create_all`` with
``alembic upgrade head`` so the tests exercise the same schema production gets.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

TEST_DB_ENV = "TIBER_TEST_DATABASE_URL"


def pytest_collection_modifyitems(config, items) -> None:
    """Skip the e2e suite unless a test database is configured."""
    if os.getenv(TEST_DB_ENV):
        return

    skip = pytest.mark.skip(
        reason=f"e2e: set {TEST_DB_ENV} to a dedicated Postgres database to run"
    )
    for item in items:
        if "/tests/e2e/" in str(item.path).replace("\\", "/"):
            item.add_marker(skip)


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Create the schema for one test, then drop it.

    Enum types are created explicitly: the models declare them with
    ``create_type=False`` (the database owns them in production), so
    ``create_all`` would otherwise fail on the first enum-typed column.
    """
    from tiber.infrastructure.models import types as model_types
    from tiber.infrastructure.models.base import Base

    engine = create_async_engine(os.environ[TEST_DB_ENV], poolclass=NullPool)
    enums = [
        value
        for value in vars(model_types).values()
        if isinstance(value, postgresql.ENUM)
    ]

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        for enum in enums:
            await conn.run_sync(
                lambda sync_conn, enum_type=enum: enum_type.create(
                    sync_conn, checkfirst=True
                )
            )
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """One session for the request handlers and the fixtures to share."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
        await db_session.rollback()


@pytest.fixture
async def project(session: AsyncSession):
    """Create a committed account + project; the account is a tenancy root, not an auth test."""
    from tiber.infrastructure.models import AccountModel, ProjectModel

    account = AccountModel(email=f"e2e-{uuid4().hex}@example.com")
    session.add(account)
    await session.flush()

    project = ProjectModel(
        account_id=account.id,
        name="E2E",
        slug=f"e2e-{uuid4().hex[:12]}",
    )
    session.add(project)
    await session.commit()
    return project


@pytest.fixture
def api_module():
    """Import the app lazily so collection succeeds while the wiring is incomplete."""
    try:
        from tiber.api import main
    except ModuleNotFoundError as exc:
        pytest.skip(f"API cannot be imported yet: missing module {exc.name}")
    return main


@pytest.fixture
def app(api_module, session: AsyncSession, project):
    """Build the real app with only the documented stand-ins overridden."""
    from tiber.api import dependencies as deps

    class _AllowAllLimiter:
        async def is_allowed(self, project_id) -> bool:
            return True

    application = api_module.create_app()

    async def _db():
        yield session

    application.dependency_overrides[deps.get_db] = _db
    application.dependency_overrides[deps.get_authenticated_project] = lambda: project
    application.dependency_overrides[deps.get_ingestion_rate_limiter] = lambda: (
        _AllowAllLimiter()
    )
    return application


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    """ASGI client; no lifespan, so the app's global engine is never touched."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://tiber.test") as http:
        yield http
