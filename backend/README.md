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

## Authentication and rate limits

The API supports dashboard JWTs and project-scoped API keys. Accounts sign up
with email/password, verify their email before receiving a session, and use
short-lived access tokens with single-use rotating refresh tokens. GitHub OAuth
is optional and requires `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`,
and `GITHUB_OAUTH_REDIRECT_URI`. Email verification uses a six-digit code,
while password reset uses a single-use link. Both require a
live `EMAIL_PROVIDER=resend`, its API key, and `EMAIL_SENDER`;
the `mock` notification provider deliberately cannot deliver authentication
messages.

Project API keys are created through the dashboard-authenticated
`/v1/projects/{project_id}/api-keys` endpoints. The raw key is returned only
once; only its SHA-256 hash is stored. API-key requests are authorized against
the key's actual project, and dashboard JWT requests against the account that
owns the project.

Rate-limit counters are separate even where budgets currently match:

- unauthenticated authentication endpoints: client IP (`auth`);
- account-level dashboard endpoints: account ID (`dashboard`);
- project routes, whether authenticated by dashboard JWT or API key: project ID
  (`api`).

The auth, dashboard, and API budgets are configured with the
`RATE_LIMIT_*_REQUESTS` and `RATE_LIMIT_*_WINDOW_SECONDS` settings. All policies
fail closed when Redis cannot provide a decision. Client IPs come from the ASGI
connection; `X-Forwarded-For` is not trusted by the application.

## Notification delivery

The API writes each accepted intake and its outbox row in the same PostgreSQL
transaction. The `beat` service schedules an outbox relay; the relay publishes
intakes to the worker, which expands them into notification rows and dispatch
outbox rows. A later relay pass publishes due notification jobs to the
channel-specific Celery queues. Run both the `worker` and `beat` services for
delivery to progress.

Until a real decision-model adapter is configured, intake processing uses
deterministic domain defaults; no LLM credentials are needed for the send path.

Outbox and worker delivery are at-least-once. Consumers use database state and
conditional claims to make duplicate jobs safe; a provider timeout after it has
accepted a message can still result in a duplicate external send on retry.
Outbox publication errors use bounded exponential retries; rows exceeding the
configured limit remain in the database with `dead_lettered_at` and
`last_error` for operator inspection.
If a worker dies after claiming a notification, the delivery worker re-queues
it until its processing lease expires, then atomically reclaims it.
Each Celery worker process reuses one asyncio loop so SQLAlchemy's pooled async
connections stay attached to their creating loop across tasks.

Configure live providers with `EMAIL_PROVIDER=resend`,
`PUSH_PROVIDER=fcm`, or `SMS_PROVIDER=twilio`, and provide the matching
credentials from `.env.example`. The default `mock` email, push, and SMS
providers are intended for local development. In-app delivery records the
notification in the existing project notification feed and needs no external
provider credentials.

### Database migrations

Set `DATABASE_URL` to the intended PostgreSQL database, then run
`uv run alembic upgrade head` from `backend/`. The migration chain installs the
required extensions, creates the core schema, adds authentication state and API
keys, and creates the notification outbox. The core-schema migration follows the
existing `2d9adfec7c5d` extension-only revision, so databases already stamped at
that revision can be migrated forward without dropping their data.
