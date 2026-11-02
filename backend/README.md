# Backend testing

Tests are grouped by scope:

- `tests/unit/` contains the fast, isolated tests.
- `tests/integration/` exercises the PostgreSQL repository and Redis rate
  limiter against real services.
- `tests/e2e/` drives the ASGI application through its HTTP contract against
  PostgreSQL. Authentication and the default rate limiter are overridden by
  the harness; see `tests/e2e/conftest.py` for those boundaries.

Run the unit suite without external services:

```bash
uv run pytest tests/unit
```

Run the integration suite with disposable PostgreSQL and Redis instances:

```bash
TIBER_INTEGRATION_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/tiber_test \
TIBER_INTEGRATION_REDIS_URL=redis://localhost:6379/15 \
uv run pytest tests/integration
```

Run the end-to-end suite with a **dedicated disposable PostgreSQL database**.
The harness creates and drops its tables:

```bash
TIBER_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/tiber_e2e \
uv run pytest tests/e2e
```

Running `uv run pytest` collects all three suites. Integration and end-to-end
tests skip with an explicit reason when their service URL is not configured.
CI provisions PostgreSQL and Redis and runs all suites with those services.
