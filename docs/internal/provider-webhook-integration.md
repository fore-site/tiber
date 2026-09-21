# Provider Webhook Integration

**Audience:** Tiber engineers and infrastructure operators
**Scope:** Internal — not customer-facing. Do not reference this document in the OpenAPI spec or customer documentation.

---

## Purpose

Delivery providers (Resend, SendGrid, FCM) send inbound HTTP callbacks to Tiber when engagement events occur — a recipient opens an email, clicks a link, a message bounces, or a recipient unsubscribes. This document describes how Tiber receives, validates, and processes those callbacks.

This is distinct from outbound webhook callbacks, which Tiber fires to *client applications* when notification lifecycle events occur. That flow is documented in the customer-facing OpenAPI spec under the Webhooks tag.

---

## Architecture Overview

```
Provider                    Tiber API Service              RabbitMQ
(Resend / FCM / SendGrid)
        │                          │                           │
        │  POST /internal/         │                           │
        │  providers/webhooks      │                           │
        │ ─────────────────────── ▶│                           │
        │                          │  1. Verify signature      │
        │                          │  2. Validate payload      │
        │                          │  3. Normalise to          │
        │                          │     EngagementEvent       │
        │                          │  4. Publish to            │
        │                          │     engagement.exchange   │
        │                          │ ────────────────────────▶ │
        │  200 OK                  │                           │
        │ ◀─────────────────────── │                           │
                                                               │
                                               ML Engine       │
                                               Engagement      │
                                               Tracker         │
                                                    │ ◀──────── │
                                                    │
                                                    ▼
                                               durable database
                                           engagement_events
```

---

## Inbound Endpoint

```
POST /internal/providers/webhooks
```

This endpoint is **not versioned** and **not prefixed with `/v1/`**. It is an internal integration surface, not a public API resource. It should be:

- Rate limited independently from the public API
- Not included in the OpenAPI spec served to customers
- Protected at the infrastructure level (firewall, allowlist by provider IP range where possible) in addition to signature verification

### Response contract

Tiber always returns `200 OK` as quickly as possible after signature verification and enqueuing — even if downstream processing fails. Providers interpret non-2xx responses as delivery failures and will retry, which can cause duplicate event delivery. The idempotency strategy for handling duplicates is described below.

Never return `500` to a provider. If internal processing fails after signature verification, log the error, return `200`, and let the dead-letter queue handle it.

---

## Provider Configuration

### Resend

**Webhook events to subscribe:**
- `email.opened`
- `email.clicked`
- `email.bounced`
- `email.delivery_delayed`
- `email.spam_complaint` (maps to `unsubscribe`)

**Endpoint to register in Resend dashboard:**
```
https://api.tiber.dev/internal/providers/webhooks
```

**Signature verification:**
Resend signs payloads using HMAC-SHA256. The signature is in the `svix-signature` header alongside `svix-id` and `svix-timestamp`. Tiber uses the [Svix](https://docs.svix.com/receiving/verifying-payloads/how) webhook verification library.

**Required environment variable:**
```
RESEND_WEBHOOK_SECRET=whsec_xxxxx
```

**Payload shape:**
```json
{
  "type": "email.opened",
  "created_at": "2026-01-01T09:00:00.000Z",
  "data": {
    "email_id": "re_abc123",
    "to": ["user@example.com"],
    "subject": "Your order has shipped"
  }
}
```

**Event type mapping:**

| Resend event | Tiber EngagementEventType |
|---|---|
| `email.opened` | `open` |
| `email.clicked` | `click` |
| `email.bounced` | `bounce` |
| `email.spam_complaint` | `unsubscribe` |
| `email.delivery_delayed` | — (logged, not recorded as engagement event) |

---

### SendGrid

**Webhook events to subscribe:**
- `open`
- `click`
- `bounce`
- `unsubscribe`
- `spamreport` (maps to `unsubscribe`)

**Endpoint to register in SendGrid dashboard:**
```
https://api.tiber.dev/internal/providers/webhooks
```

**Signature verification:**
SendGrid signs payloads using ECDSA with a public key available from the SendGrid dashboard. The signature is in the `X-Twilio-Email-Event-Webhook-Signature` header and the timestamp in `X-Twilio-Email-Event-Webhook-Timestamp`.

**Required environment variable:**
```
SENDGRID_WEBHOOK_PUBLIC_KEY=MFkwEwYH...
```

**Payload shape:**
SendGrid sends an array of events per request:
```json
[
  {
    "email": "user@example.com",
    "event": "open",
    "timestamp": 1735722000,
    "sg_message_id": "sendgrid_message_id.filter-abc123",
    "useragent": "Mozilla/5.0..."
  }
]
```

**Event type mapping:**

| SendGrid event | Tiber EngagementEventType |
|---|---|
| `open` | `open` |
| `click` | `click` |
| `bounce` | `bounce` |
| `unsubscribe` | `unsubscribe` |
| `spamreport` | `unsubscribe` |
| `deferred` | — (logged, not recorded as engagement event) |
| `delivered` | — (handled by delivery tracking, not engagement) |

---

### FCM (Firebase Cloud Messaging)

FCM does not send engagement webhooks in the same model as email providers. Push notification open and interaction events are tracked client-side by the application and reported back to Tiber via a dedicated client-side event endpoint.

**Client-side event endpoint (customer-facing):**
```
POST /v1/projects/{project_id}/notifications/{notification_id}/engagement-events
```

This is the one inbound engagement path that is customer-facing and will be added to the OpenAPI spec when push notification engagement tracking is implemented in Phase 7.

---

## Payload Normalisation

All inbound provider payloads are normalised to a canonical `EngagementEvent` before being published to RabbitMQ. This normalisation happens inside the inbound handler and is the only place provider-specific payload shapes are referenced.

The normalisation steps are:

1. **Resolve `notification_id`** — look up the Tiber notification by the provider's message ID (e.g. Resend's `email_id`, SendGrid's `sg_message_id`). These IDs are stored in `delivery_attempts.provider_message_id`. If no match is found, log the event with the provider message ID and return `200` — unmatched events are expected (e.g. emails sent before Tiber started recording provider IDs).

2. **Resolve `recipient_id` and `project_id`** — derive from the matched notification.

3. **Map event type** — apply the provider-specific mapping table above.

4. **Set `occurred_at`** — use the provider's event timestamp, not Tiber's processing time. For Resend, this is `created_at`. For SendGrid, this is `timestamp` (Unix epoch, convert to ISO 8601). `occurred_at` is what the ML Send-Time Predictor trains on.

5. **Set `is_synthetic: false`** — all events arriving via this endpoint are real provider events.

6. **Set `correlation_id`** — derive from the matched notification's `correlation_id` so the event is traceable through the full pipeline.

---

## Idempotency

Providers retry failed webhook deliveries, and network issues can cause duplicate deliveries even when Tiber returns `200`. The idempotency strategy is:

- Use the provider's event identifier as a deduplication key (Resend's `svix-id`, SendGrid's `sg_event_id`)
- Check this key in Redis before processing with a 48-hour TTL
- If the key exists, return `200` immediately without re-publishing to RabbitMQ

**Redis key pattern:**
```
engagement:inbound:{provider}:{provider_event_id}
```

This is separate from the notification submission idempotency keys in `idempotency:{project_id}:{key}` and should not share the same TTL or namespace.

---

## Security

### Signature verification order

1. Extract the signature header for the provider
2. Verify the signature before doing anything else — before database lookups, before Redis checks, before logging the payload content
3. Return `401` immediately if verification fails — do not log the payload body on failure (it may be a probe)
4. After verification passes, proceed with normalisation and enqueuing

A failed signature should never reach the engagement queue. The inbound endpoint is the trust boundary.

### IP allowlisting

Where providers publish their outbound IP ranges, configure firewall rules to allowlist only those ranges on the `/internal/` path. This is a defence-in-depth measure alongside signature verification, not a replacement for it.

**Provider IP range documentation:**
- Resend: published at `https://resend.com/docs/webhooks/ip-allowlisting`
- SendGrid: published at `https://sendgrid.com/docs/for-developers/tracking-events/getting-started-event-webhook-security-features/`
- FCM: not applicable (client-side model)

---

## Error Handling

| Scenario | Response | Action |
|---|---|---|
| Signature verification fails | `401` | Log provider and header (not body). Do not enqueue. |
| Payload missing required fields | `200` | Log warning with provider message ID. Do not enqueue. |
| Notification ID not found | `200` | Log with provider message ID. Do not enqueue. |
| Redis unavailable (idempotency check fails) | `200` | Log warning. Proceed with enqueuing. Accept potential duplicate. |
| RabbitMQ unavailable | `200` | Log error with full payload. Write to a fallback durable database table for replay. |
| Duplicate event (idempotency key exists) | `200` | Log at debug level. Return immediately. |

The RabbitMQ unavailability case is the most critical. If the engagement queue is down and events are dropped, ML training data is permanently lost. The fallback durable database table (`engagement_inbound_fallback`) acts as a dead-letter store for manual replay once the broker recovers.

---

## Environment Variables Summary

| Variable | Required for | Description |
|---|---|---|
| `RESEND_WEBHOOK_SECRET` | Resend | HMAC-SHA256 signing secret from Resend dashboard |
| `SENDGRID_WEBHOOK_PUBLIC_KEY` | SendGrid | ECDSA public key from SendGrid Event Webhook settings |
| `PROVIDER_WEBHOOK_RATE_LIMIT` | All | Max inbound requests per minute (default: 1000) |
