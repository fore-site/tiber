# 08 — Send Contract & Identity Model

**Status:** Accepted (domain + persistence implemented; API contract rewrite pending)
**Date:** 2026-09-18
**Supersedes:** the per-send `context` field decision; the parked "supersession field" idea
**Related:** 03 (API service), 05 (ML engine — feature inventory), 06 (domain model)

## Context

Clients asked for less integration work: fewer payload fields, fewer dashboard
steps, more inferred behavior from Tiber. Analysis of what actually produces
that experience showed that most "magic" is not intelligence but *defaults
resolved from identity*: accept natural names instead of internal UUIDs, fill
in the rest from what is already stored, and learn from signals Tiber already
sees. Machine learning is only one source of fill-in; most of it is lookup.

Three earlier decisions shaped this record:

- The **authorship constitution**: Tiber decides when, how urgent, which
  channel, whether at all — it never authors content. There is no LLM
  anywhere in Tiber.
- `send_time_basis` is stored provenance state, classified once at intake.
- `correlation_id` is a per-request pipeline trace, **not** a grouping key.

## Decisions

### D1 — Client-database access: never

Tiber does not read client databases, even opt-in. Trust and liability costs
(a notification vendor reading a production users table) vastly exceed the
benefit, and the useful training signal (opens, clicks, bounces) already
flows through Tiber. Static facts about a recipient (timezone, language,
plan) live on the recipient profile, set once and updated when they change —
never re-sent per notification.

### D2 — Recipients are addressed by client identity or raw address

The client's own id (their `external_id`) or a channel address — never a
Tiber UUID, and never both in one payload (422). The payload uses two named
fields so intent is explicit and the ambiguity of a polymorphic string is
avoided:

- `"recipient": "user_12345"` — string external_id. Unknown → **404**.
- `"address": { "email": "jane@x.com" }` — object keyed by channel, so the
  channel is the key and no separate `channel` field is needed here.

Address sends are **address-matched** against registered recipients first:
a raw address that belongs to a registered recipient *is* that recipient —
their opt-outs apply and their engagement history grows. This closes the
opt-out side door (an opted-out human must not be reachable by omitting
their id).

**Unknown addresses auto-create an ownerless recipient profile** (default
preferences, no external_id) and the send proceeds. Sending may create an
ownerless profile; **attaching a human identity is always an explicit act**:

- Registration is its own endpoint — no register-and-send in one call.
- Registering with an address owned by an ownerless profile **claims** it:
  attaches the external_id and re-points engagement history.
- Registering with an address owned by a **different registered** recipient
  → **409**, with a message that must not reveal who owns the address.

**Prerequisites (uniqueness rules):** `external_id` unique per project;
`(project, channel, address)` unique. The latter is load-bearing twice:
it makes ownerless auto-create idempotent under concurrent racing sends
(insert-then-catch-collision, not check-then-insert) and it is what detects
the 409 condition. Uniqueness itself is a boundary-only guarantee: the
entity cannot and should not verify it.

**Identity gap, accepted:** one human arriving on two channels before any
registration is two ownerless profiles; global opt-outs do not propagate
across them until the claim flow unifies them. The repair path is the
claim, not inference — Tiber does not guess identity.

**Privacy note:** auto-created profiles mean Tiber persistently stores
contact details for people who never explicitly registered. Clients
already supplied those addresses per send; the retention policy for
ownerless profiles must be recorded in the dashboard/API docs.

### D3 — Topics are optional and carry a default category

Clients may pass a topic *name* (`"topic": "newsletter"`); Tiber resolves
it per project, auto-creating it on first use, and takes the category from
the topic's declared default. `NotificationTopic` already exists with a
declared `category`. A client may also send with **no topic**, declaring
only the category. An explicit per-send category overrides the topic
default.

**The line that keeps this compliant:** the client still makes the
compliance decision — once, at topic level, by declaring. Inference must
never escalate a category upward (nothing becomes CRITICAL by guess); a
guess, if ever introduced for un-declared topics, may only make delivery
more restricted, never less.

### D4 — Channel is optional

When absent, Tiber picks from the recipient's registered, non-opted-out
addresses by a fixed priority (initially email → push → sms, adjustable
per project). ML channel selection may later occupy the same missing
field. Explicit channel, when given, is honored.

**Policy interaction, recorded:** a channel override changes which policy
rules apply (restricted windows are per-channel), so any future predicted
channel must re-enter the policy chain. That constraint belongs to doc 05.

### D5 — `context` is retired

The per-send ML feature payload is deleted from the entity. Static facts
moved to the recipient profile (D1); learned behavior comes from
engagement events. `Notification.context`, its validation block, and its
`create()`/`reconstitute()` parameters are removed. Do not reintroduce it.

### D6 — `group_key`: opaque identity of "the same logical thing"

Optional, opaque, client-supplied string on the notification and payload.
`order-1234-confirm` (an idempotency key) answers *"is this the same send,
retried?"*; `order-1234` (a group key) answers *"is this about the same
thing?"* — retry identity vs. entity identity.

Distinct from `topic` (the stream) and `correlation_id` (the pipeline
trace). Opaque means opaque: Tiber stores and indexes it, never parses
structure from it. If a feature needs to read meaning out of the key, the
feature needs a real field — that is the smell test.

Ships **inert but consumer-locked** (nullable column, indexed
`(project, recipient_id, group_key)`). Named future consumers: digest
collapse ("5 new comments on X" = count of sends sharing a group key in a
window), dedup refinement (`(recipient, group_key, window)`), per-entity
learning ("ignored the last 4 notifications about X" — the index's first
reader).

**Supersession is replaced by "latest-wins on group":** a per-topic or
per-group delivery policy under which only the newest send in a group may
be delivered and older pending ones are auto-cancelled — with their
generated cancellation reason recorded. The client just keeps sending;
no supersede reference ever enters the payload. Gated on client consent
(auto-cancelling a client's notification is suppression-stakes), exempt
for CRITICAL, and open fork at implementation time: whether an
*explicitly scheduled* send may be cancelled by a newer send.

### D7 — Cancellation reasons are optional

`mark_cancelled(reason: str | None = None)`. A client may cancel freely
without documenting why — that is their prerogative and none of Tiber's
business. A **system-initiated** cancellation (digest absorption, D6
latest-wins) must supply the reason it generated: there the reason is a
system fact Tiber produced, not client documentation. The reason is only
representable on a CANCELLED row.

## The contract

Minimum viable payloads:

```json
{ "recipient": "user_12345", "topic": "newsletter", "content": { "title": "...", "body": "..." } }
{ "address": { "email": "jane@x.com" }, "content": { "body": "..." } }
```

Full field map:

| Field | Status | Resolution when absent |
|---|---|---|
| `recipient` / `address` | exactly one, required | — |
| `content` | required | — |
| `topic` | optional | category must be given directly |
| `category` | required iff topic absent; explicit beats topic default | — |
| `channel` | optional | Tiber picks (D4 priority) |
| `group_key` | optional, opaque | — |
| `send_at` | optional | basis classified at intake (CRITICAL → IMMEDIATE, others → ML_PREDICTED) |
| `idempotency_key` | optional | — |

`context` is retired (D5). The principle in one line: **the client's
payload answers what and to whom; Tiber derives which group, which
channel, and when — every default overridable, every identity decision
explicit.**

## Digest assembly (design, pre-implementation)

A digest's "smart one-liner" is not generated — it is assembled:

| Piece | Source |
|---|---|
| "3 new" | COUNT of sends sharing a `group_key` in the window |
| "comments on" | fixed template text |
| "'Deploy is live'" | the client's own content (member title) |
| Item lines | each member notification's client-authored content |
| Subject | template + count + topic name |

Pipeline: window closes for `(recipient, topic)` on a digest policy →
collect PENDING batched-category notifications → collapse by `group_key`
→ rank (Digest Ranker, per-item engagement signal) → render per-channel
template **with a tracked link per item** (that link requirement is what
makes the ranker trainable). SMS holds no digest; batched categories
either exclude it or collapse to a single line.

The constitution holds by construction: Tiber assembles the client's own
words; it never authors. A client wanting an LLM-written summary may
generate it themselves before sending — that is outside Tiber's pipeline.

**Open fork, deliberate at digest phase:** when the digest delivers, what
status do the member notifications take? DELIVERED is arguably honest
(content was delivered inside the digest) or arguably a lie (item 4 was
not individually seen). The choice touches attribution and the ranker's
training data. Related: `(send_at=None, ML_PREDICTED)` is a representable
stuck state — alert threshold at ML phase.

## Implementation state

- [x] `Notification.group_key` (entity + column + mappings + rehydration)
- [x] `cancellation_reason` column; `mark_cancelled` optional reason (D7)
- [x] `context` deleted (entity, validation, create/reconstitute, repo note)
- [x] `mark_cancelled(reason)` prerequisite for latest-wins (D6/D7)
- [ ] `external_id` unique per project; `(project, channel, address)` unique
- [ ] Topic name uniqueness per project; persistence model for topics
- [ ] API contract rewrite (both endpoints) to the field map above
- [ ] Claim flow: ownerless adoption + engagement-event re-pointing
- [ ] Digest vocabulary (digest policy, member-status fork, rendering)
