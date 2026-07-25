# Redis Cache Specification

**Audience:** Tiber engineers
**Scope:** All Redis key patterns, TTL values, value formats, access patterns, cache strategies, and failure behaviour.

Redis is a dependency for Tiber's authentication layer. If Redis is unreachable, the API Service fallls back to Postgres in some instances and fails close in others such as jwt revocation.

---

## Namespace Convention

All key strings are constructed exclusively inside `core/redis.py:RedisKeys`. No Redis key string is ever constructed elsewhere in the codebase.

```
auth:jwt:blocklist:{jti}              JWT access token blocklist
auth:refresh:{token_id}               Refresh token store
auth:apikey:context:{key_hash}        API key auth context cache
auth:apikey:revoked:{key_hash}        API key revocation signal
idempotency:{project_id}:{key}        Idempotency response cache
```

---

## 1. JWT Authentication

### 1.1 Access Token Blocklist

#### Purpose

JWT access tokens are stateless and verified by signature. On logout or forced revocation, the token's `jti` (unique token identifier, a UUID embedded in the JWT payload) is written to the blocklist. The auth middleware checks this after verifying the signature and before granting access.

**Signature verification always runs before any Redis check.** A token with an invalid signature is rejected before touching Redis.

#### Key

```
auth:jwt:blocklist:{jti}
```

#### Value

```
1
```

The presence of the key is the signal. The value carries no semantic meaning — `1` is the smallest valid Redis string.

#### TTL

```python
TTL = max(1, token_exp - int(time.time()))  # remaining lifetime in seconds
```

The TTL is the token's remaining lifetime at the moment of revocation, not the full configured access token expiry. After a token's natural expiry the `exp` claim in the JWT causes rejection before any Redis check — the blocklist entry is redundant past that point. Aligning TTL to remaining lifetime means entries self-clean at the exact moment they become unnecessary.

Maximum TTL: 900 seconds (15 minutes — the configured access token lifetime).

#### Access Pattern

```
Write:  SET auth:jwt:blocklist:{jti} 1 EX {remaining_ttl}
Read:   EXISTS auth:jwt:blocklist:{jti}
```

Read runs on every authenticated request. Write runs only on logout or admin-forced revocation.

#### Failure Behaviour

Fail closed. If Redis is unreachable during a read, return 503 — do not skip the blocklist check. If Redis is unreachable during a write (logout), return 503 — the client must know the revocation did not complete.

---

### 1.2 Refresh Token Store

#### Purpose

Refresh tokens are long-lived credentials used to obtain new access tokens. Storing them in Redis enables immediate revocation and rotation — each use of a refresh token issues a new one and invalidates the old, preventing replay attacks.

#### Key

```
auth:refresh:{token}
```

`token` is a url-safe random string generated at refresh token creation time.

#### Value

```json
{
  "user_id": "uuid"
  }
```

`user_id` which is the unique identifier of the user is stored in the cache value so the token refresh endpoint can load the user context without a Postgres lookup on the happy path.

#### TTL

```
7 days (604_800 seconds)
```

Matches the configured refresh token lifetime (`REFRESH_TOKEN_EXPIRE_DAYS = 7`). The TTL and the JWT `exp` claim are intentionally aligned — the Redis entry is the live session record. When the entry expires, the refresh token is dead regardless of the JWT signature.

#### Access Pattern

```
Write:   SET auth:refresh:{token} {json_value} EX 604800
Read:    GET auth:refresh:{token}
Delete:  DEL auth:refresh:{token}    ← on logout or rotation
```

**On token rotation** (refresh endpoint called):

Steps 1–3 must be atomic. Use a Redis pipeline to prevent a window where both the old and new tokens are simultaneously invalid:

```python
pipe = redis.pipeline()
pipe.delete(old_token_key)
pipe.set(new_token_key, new_value, ex=604800)
pipe.execute()
```

On logout, both the access token JTI and the refresh token ID are invalidated in a single pipeline:

```python
pipe = redis.pipeline()
pipe.set(f"auth:jwt:blocklist:{jti}", 1, ex=remaining_ttl)
pipe.delete(f"auth:refresh:{token_id}")
pipe.execute()
```

#### Failure Behaviour

Fail closed. Refresh token operations require Redis. A 503 during token refresh is preferable to issuing a new token without invalidating the old one.

---

## 2. API Key Authentication

### 2.1 Single Entry Design

API key authentication uses a **single Redis entry per key** that encodes two possible states: `valid` (auth context) and `revoked` (revocation signal). This eliminates the need for two separate Redis lookups per request — one `GET` determines the outcome regardless of state.

The state field in the value drives the authentication decision. The TTL is determined by the state at write time.

#### Key

```
auth:apikey:{key_hash}
```

`key_hash` is the 64-character SHA-256 hex hash of the raw `tb_xxxxx` API key. The middleware computes this from the Authorization header before any Redis or Postgres call — no round trip needed to determine the key to look up.

#### Value — Valid State

```json
{
  "state": "valid",
  "key_id": "uuid",
  "project_id": "uuid",
  "expires_at": "2027-01-01T00:00:00Z" | null
}
```

#### Value — Revoked State

```json
{
  "state": "revoked",
  "revoked_at": "2026-01-01T00:00:00Z"
}
```

#### Value — Not Found

```json
{
  "state": "not_found",
}
```

#### TTL

| State | TTL | Rationale |
|---|---|---|
| `valid` | 5 minutes (300 seconds) | Short enough that key updates (expiry, revocation) propagate quickly. Long enough to eliminate Postgres load for active clients making repeated requests. |
| `revoked` | 30 days (2_592_000 seconds) | API keys have no natural expiry to derive a TTL from. 30 days covers the practical replay threat window. After expiry, the Postgres `revoked_at` column is the permanent authoritative record. |
| `not_found` | 60 seconds | Short enough to protect from high frequency spam. |

For keys with `expires_at` set, the `valid` state TTL is `min(300, max(1, expires_at_unix - now_unix))` — the entry expires no later than the key itself.

---

### 2.2 Cache-Aside Authentication Flow

Cache-aside means the cache is never pre-populated. Entries are written only when a Postgres lookup produces a result. The application checks the cache first and falls back to Postgres on a miss.

```
Step 1 — Compute cache key
    key_hash = sha256(raw_key).hexdigest()
    cache_key = f"auth:apikey:{key_hash}"

Step 2 — Read single cache entry
    GET auth:apikey:{key_hash}

    ┌─────────────────────────────────────────────────────────┐
    │ MISS (nil)                                              │
    │   → Step 3: Query Postgres                              │
    ├─────────────────────────────────────────────────────────┤
    │ HIT, state == "revoked"                                 │
    │   → 401 Unauthorized                                    │
    ├─────────────────────────────────────────────────────────┤
    │ HIT, state == "valid"                                   │
    │   expires_at present and < now → 401 Unauthorized       │
    │   otherwise → return (key_id, project_id) → allow       │
    └─────────────────────────────────────────────────────────┘

Step 3 — Postgres lookup (cache miss path only)
    SELECT id, project_id, revoked_at, expires_at
    FROM api_keys WHERE key_hash = $1

    → Not found:
        return 401 Unauthorized
        SET auth:apikey:{key_hash} {"state":"not_found"} EX 60

    → Found, revoked_at IS NOT NULL:
        SET auth:apikey:{key_hash} {"state":"revoked", ...} EX 2592000
        return 401 Unauthorized

    → Found, expires_at IS NOT NULL AND expires_at < now:
        return 401 Unauthorized

    → Found, valid:
        SET auth:apikey:{key_hash} {"state":"valid", ...} EX 300
        return (key_id, project_id) → allow
```

---

### 2.3 Revocation Flow

When a client calls `DELETE /v1/projects/{project_id}/api-keys/{key_id}`, Postgres and Redis are written atomically from the caller's perspective. If either write fails, the operation is rejected and no partial state is committed.

```
Step 1 — Retrieve key_hash from Postgres
    SELECT key_hash FROM api_keys
    WHERE id = $1 AND project_id = $2

Step 2 — Write Postgres and Redis together
    BEGIN Postgres transaction
        UPDATE api_keys SET revoked_at = NOW() WHERE id = $1
    COMMIT

    SET auth:apikey:{key_hash}
        {"state": "revoked", "revoked_at": now_iso8601}
        EX 2592000
    (overwrites any existing valid context entry)

    If Redis write fails:
        ROLLBACK Postgres transaction
        return 503
```

The overwrite is the key mechanism. Whether the entry previously held a valid context (5-minute TTL, populated from a prior request) or was absent entirely, the `SET` replaces it with the revoked marker at the 30-day TTL. A subsequent request reading this entry hits the `state == "revoked"` branch and receives 401 immediately — no Postgres lookup.

**On overwrite failure:** Postgres is rolled back. The key remains valid. The client receives 503 and retries. This is preferable to a state where Postgres marks the key revoked but Redis still serves it as valid.

---

### 2.4 Entry Lifecycle

```
Key created           →  no Redis entry (cache is lazy-loaded)
First request         →  MISS → Postgres lookup → write valid entry (5 min TTL)
Repeat requests       →  HIT, state valid → allow (no Postgres)
Entry expires (5 min) →  MISS → Postgres lookup → write valid entry (5 min TTL)
Key revoked           →  valid entry overwritten with revoked entry (30 day TTL)
Post-revocation reqs  →  HIT, state revoked → 401 (no Postgres)
30 days post-rev      →  entry expires → MISS → Postgres lookup → revoked confirmed
```

---

## 3. Idempotency Cache

### Purpose

Caches the response of the first successful `POST /v1/projects/{project_id}/notifications` request for a given `Idempotency-Key` header. Duplicate submissions within the TTL window return the original cached response without re-processing — no second Postgres write, no second RabbitMQ publish.

### Key

```
idempotency:{project_id}:{idempotency_key}
```

`project_id` namespaces the key so two different projects can use the same idempotency key string without conflict. The raw `idempotency_key` is the exact value from the `Idempotency-Key` request header.

### Value

```json
{
  "status_code": 201,
  "body": {
    "id": "uuid",
    "status": "pending",
    "correlation_id": "uuid",
    "channel": "email",
    ...
  }
}
```

The full original response — both status code and response body — is cached so duplicate requests receive an exact replica of the original 201 response, including the notification `id` and `correlation_id`.

### TTL

```
24 hours (86_400 seconds)
```

24 hours is the standard industry convention (used by Stripe, Resend, and others). It balances two concerns:

- **Too short:** A client that retries after a long delay gets a new notification created rather than the original response — the idempotency guarantee is violated.
- **Too long:** Redis memory grows proportionally. At 24 hours with high notification volume, the idempotency cache dominates Redis memory usage (see estimates below). If memory becomes a constraint, this is the primary lever — reducing to 6 hours cuts idempotency memory by 75%.

### Access Pattern

```
Write:  SET idempotency:{project_id}:{key} {json_value} EX 86400 NX
Read:   GET idempotency:{project_id}:{key}
```

`NX` (set if not exists) on the write is critical. It prevents a race condition where two concurrent requests with the same idempotency key both read a cache miss and both attempt to process. Only the first writer succeeds — the second finds an existing entry and returns the cached response.

### First Submission Flow

```
1. GET idempotency:{project_id}:{key}  → nil (cache miss)
2. Validate and process the notification
3. Persist to Postgres
4. Publish to RabbitMQ
5. SET idempotency:{project_id}:{key} {response} EX 86400 NX
6. Return 201
```

### Duplicate Submission Flow

```
1. GET idempotency:{project_id}:{key}  → cached response (cache hit)
2. Return original status code and body immediately
   (no Postgres write, no RabbitMQ publish)
```

The duplicate returns the original `201`, not a `409`. From the client's perspective the notification was accepted — returning `409` would require clients to handle "already submitted" as a distinct error case, adding unnecessary complexity to retry logic.

### Key Sanitisation

The raw `Idempotency-Key` header value must be sanitised before constructing the Redis key:

- Strip leading and trailing whitespace
- Enforce maximum length of 255 characters
- Reject values containing `:` — colons corrupt the key pattern
- Reject empty strings

Sanitisation failures return `422 Unprocessable Entity`.

### Failure Behaviour

**Fail closed.** If Redis is unreachable when checking for a cached idempotency response, return 503. Do not fall through to Postgres to "check if this looks like a duplicate" — that path is unreliable and processing a duplicate notification has real consequences for the end recipient. A temporary 503 is preferable to a duplicate message delivery.

---

## Key Summary

| Key | TTL | Written on | Deleted on |
|---|---|---|---|
| `auth:jwt:blocklist:{jti}` | Remaining token lifetime (max 900s) | Logout / forced revocation | TTL expiry |
| `auth:refresh:{token_id}` | 7 days | Login / token rotation | Logout / rotation |
| `auth:apikey:{key_hash}` | 5 minutes for valid state, 30 days for revoked state | First valid Postgres lookup | Revocation for valid or TTL expiry for already revoked|
| `idempotency:{project_id}:{key}` | 24 hours | First successful notification POST | TTL expiry |

---

## Failure Behaviour Summary

| Concern | Redis unavailable — read | Redis unavailable — write |
|---|---|---|
| JWT blocklist | Fail closed — 503 | Fail closed — 503, logout rejected |
| Refresh tokens | Fail closed — 503 | Fail closed — 503, refresh rejected |
| API key context | Fail closed — 503 | Log warning, continue without caching |
| API key revocation | Fail closed — 503 | Fail closed — 503, revocation rejected |
| Idempotency cache | Fail closed — 503 | Log warning, continue without caching |

**API key context cache write failure** is the one case where a write failure is non-fatal. A failed context cache write means the next request for the same key hits Postgres again — degraded performance, not degraded correctness. Log it as a warning and continue.

**Idempotency cache write failure** after a successful Postgres write is also non-fatal. The notification was created and the job was published. Log the failure with the `correlation_id`. The response is returned to the client. If they retry with the same idempotency key, they will get a second notification created — which is the failure mode we accept when caching is unavailable. This is preferable to returning 503 after a notification has already been committed.

---
