# Container Diagram

**C4 Level:** 2. Containers
**Container in focus:** N/A

---

## Purpose

This diagram shows the internal containers that make up the Tiber platform; The deployable units, their technology choices, and how they communicate with each other and with external systems. It is intended for engineers and technical reviewers who need to understand the high-level architecture before working on any individual container. It does not show internal component structure; that is the concern of the Level 3 diagrams for the API Service, Worker Service, and ML Engine.

---

## Diagram

![container diagram](../diagrams/container-diagram.svg)

---

## Key Decisions

- **RabbitMQ as the message broker over Redis:** Celery supports both Redis and RabbitMQ as brokers. RabbitMQ was chosen deliberately because it exposes exchange types, routing keys, and queue durability as first-class concepts rather than abstracting them away. This means the messaging topology, which exchange a notification job is published to, which routing key determines its queue, how dead-letter queues are bound, is explicit and engineered, not inherited from framework defaults. The tradeoff is operational complexity: RabbitMQ requires a separate hosted instance (e.g CloudAMQP free tier for deployment) whereas Redis would have doubled as both broker and cache with a single instance.

- **Redis retained alongside RabbitMQ with three distinct roles:** With RabbitMQ handling brokering, Redis serves as the auth state store (JWT blocklist, API key revocation list), rate limiting counter store, and idempotency key cache. These are genuinely different data with different TTLs and access patterns, but they share a single Redis instance for operational simplicity at this scale. Redis is a hard dependency for auth. If it is unreachable, the API Service fails closed with a 503 rather than allowing requests through with unverifiable revocation state.

- **ML Engine and AI Gateway are in-process containers, not standalone services:** Both are invoked directly by the Worker Service as Python modules rather than over HTTP or a message queue. This keeps the deployment surface small. No additional services to host, health-check, or version independently, and is appropriate given that inference latency is acceptable within the worker process for this scale. The interface boundary between the Worker and each container is designed so that either could be extracted into a standalone service behind an HTTP API in future without changing the Worker's calling code. This is documented in the Worker Service component diagram.

- **AI and ML are clearly separated containers with distinct responsibilities:** The ML Engine makes routing and timing decisions using trained scikit-learn models; Priority classification, send-time optimisation, channel preference prediction. The AI Gateway handles content decisions using LLM APIs; Summarisation, tone adaptation, subject generation. These are different kinds of intelligence with different failure modes, different latency profiles, and different update cycles. Keeping them as separate containers prevents the common mistake of conflating "AI" and "ML" into a single black box, and makes it possible to degrade or disable either independently.

- **Provider abstraction with selective live integration:** The Worker Service dispatches to a provider abstraction layer that supports all five channels (email, push, SMS, webhook, in-app) through a common interface. Email and push are fully implemented with live provider integrations. SMS, webhook delivery, and in-app are implemented as documented mock adapters that satisfy the same interface. This is a deliberate scope decision. The abstraction proves extensibility without requiring five live integrations. The decision is architecturally visible here because all providers appear as a single external system, not five separate ones.

- **PostgreSQL is the single source of truth for all persistent state:** Notifications, users, delivery logs, engagement events, ML training data, blackout dates, compliance rules, and webhook registrations all live in Postgres. Redis holds only ephemeral state with defined TTLs. This means Redis can be flushed or replaced without data loss, only active sessions, in-flight rate limit windows, and recent idempotency keys are affected.

---

## What This Diagram Does Not Show

This diagram does not show the internal structure of any container consisting of components, business capabilities, or code organisation are covered in the Level 3 diagrams. It does not show the RabbitMQ exchange and queue topology (exchanges, routing keys, dead-letter bindings).
