# Tiber Project Roadmap

**An AI/ML-augmented production-grade notification platform**

Stack: FastAPI + Celery + RabbitMQ + Redis + Postgres + S3/MinIO + scikit-learn + Next.js

## Release Plan

Each release corresponds to a completed roadmap phase. Releases are cumulative, meaning each version includes all functionality from previous versions.

| Version | Phase                                   | Status  |
| ------- | --------------------------------------- | ------- |
| v0.1.0  | Phase 1: Foundations and System Design  | Ongoing |
| v0.2.0  | Phase 2: Core Notification Engine       | Planned |
| v0.3.0  | Phase 3: Provider Abstraction           | Planned |
| v0.4.0  | Phase 4: Data Simulator                 | Planned |
| v0.5.0  | Phase 5: Machine Learning Services      | Planned |
| v0.6.0  | Phase 6: AI/LLM Services                | Planned |
| v0.7.0  | Phase 7: Platform Features and Frontend | Planned |
| v0.8.0  | Phase 8: Observability                  | Planned |
| v0.9.0  | Phase 9: Deployment, Docs, Demo         | Planned |
| v1.0.0  | Production Release                      | Planned |

### Release History

| Version | Date | Highlights      |
| ------- | ---- | --------------- |
| —       | —    | No releases yet |

## Roadmap

The roadmap is the implementation guide for the architecture in `docs/architecture/`. If a task exposes a design choice, prefer the architecture decisions over framework defaults: project-scoped resources, RabbitMQ for durable work routing, Redis only for ephemeral/auth state, Postgres as the source of truth, in-process ML/AI boundaries, and graceful degradation for intelligence features.

### Phase 1: Foundations and System Design

- [✅] Repo scaffold (monorepo: `/app`, `/dashboard`, `/docs`)
- [✅] Architecture docs and diagrams complete: context, containers, API Service, Worker Service, ML Engine, domain model, RabbitMQ topology
- [✅] API contract first (OpenAPI spec, design project-scoped routes before building)
- [ ] DB schema design from the domain model: `User`, `projects`, `api_keys`, `templates`, `recipients`, `user_preferences`, `notifications`, `delivery_attempts`, `delivery_channels`, `providers`, `webhook_endpoints`, `webhook_events`, `delivery_policies`, `engagement_events`, `model_versions`, `training_runs`
- [ ] Redis key design and TTLs for JWT blocklist, API key revocation, rate-limit counters, and idempotency cache
- [ ] Docker Compose: API + worker + Postgres + RabbitMQ + Redis + local object storage (MinIO-compatible), running locally
- [ ] `/health` distinguishes required dependencies; Redis unavailable means unhealthy because authenticated API requests fail closed
- [ ] GitHub Actions skeleton: lint (ruff) + test (pytest) on push

**Exit criteria:** `docker-compose up` gives a running API and worker with `/health`, project-scoped schema migrations, RabbitMQ/Redis/Postgres reachable, CI green on an empty test suite.

### Phase 2: Core Notification Engine

- [ ] Project-scoped `POST /notifications`: authenticate, validate, persist immutable notification, enqueue (idempotency key required)
- [ ] Idempotency Guard runs before template resolution and scheduling; duplicate keys within 24 hours return the original persisted 201 response
- [ ] Job payload follows the Worker architecture: thin payload with stable fields, `correlation_id`, `schema_version`, `scheduled_at`, `send_time_basis`, ML prediction metadata, and retry attempt state
- [ ] RabbitMQ publisher uses `notifications.exchange`, channel routing keys, durable messages, and publisher confirms
- [ ] Celery worker pipeline: Notification Processor (orchestrator), Scheduler Executor, Dispatch Policy Guard, Provider Manager, Retry Manager, Delivery Tracker
- [ ] Retry with exponential backoff via RabbitMQ retry queues; route exhausted jobs to channel-specific DLQs
- [ ] Scheduling support (send-at-time, not just immediate) and worker execution at the scheduled time
- [ ] Minimal preference and delivery-policy read model with safe defaults; full management surfaces arrive in Phase 7
- [ ] Delivery Policy Resolver at intake: user preferences first, blackout/calendar constraints second, compliance restrictions last
- [ ] Dispatch Policy Guard re-checks drift-sensitive DND/compliance constraints before delivery and re-queues on soft violations
- [ ] Rate limiting on ingestion using Redis counters
- [ ] Template rendering (basic variables into a message body) with direct-content notifications still allowed
- [ ] Delivery status tracking through immutable delivery attempts and logs
- [ ] Unit tests for business logic, integration tests for the full enqueue→deliver flow

**Exit criteria:** A project-scoped notification can be created, de-duplicated, scheduled, routed through RabbitMQ, and tracked through pending → processing → delivered/failed or policy-rejected, with retries visible in delivery attempts and DLQs.

### Phase 3: Provider Abstraction and Multi-Channel Delivery

- [ ] Define a `ChannelProvider` interface (send, health-check, capabilities)
- [ ] Email adapter : live integration (SendGrid or Resend)
- [ ] Push adapter : live integration (FCM)
- [ ] SMS, webhook, in-app adapters : built against the same interface, using mock/sandbox implementations, clearly documented as drop-in-ready
- [ ] Provider Manager returns typed success/failure outcomes only; retry/dead-letter decisions remain in the Notification Processor and Retry Manager
- [ ] Failover logic: if primary provider fails health check or delivery, fall back to secondary (can be demonstrated with email primary + a second email provider, or live/mock pairing)
- [ ] Provider health monitoring (simple periodic check + status table)
- [ ] Outbound webhook registration API and Worker Webhook Dispatcher for lifecycle callbacks (`delivered`, `failed`, `bounced`) with independent webhook retry/dead-letter handling

**Exit criteria:** The same notification can route through any of the 5 channels via one interface; failover is demonstrable end-to-end on at least one channel, and recorded delivery outcomes can trigger registered webhook callbacks without affecting the delivery record.

### Phase 4: Data Simulator

- [ ] Design 4-6 synthetic user personas (e.g. "early-bird email opener," "ignores SMS," "high engagement on push between 6-9pm")
- [ ] Simulator module generating recipients, preferences, notification history, delivery attempts, and engagement events (opened/clicked/ignored) with configurable noise
- [ ] `is_synthetic` flag so demo data and training data are never confused with real data
- [ ] Document the simulator's assumptions and design in its own README section
- [ ] Generate and sanity-check a first training dataset (plot it, don't just trust it)

**Exit criteria:** `python -m simulator generate --recipients 500 --days 90` produces a realistic, inspectable dataset you'd be comfortable explaining feature-by-feature in an interview.

### Phase 5: Machine Learning Services

- [ ] **Priority classifier**: feature engineering from content/metadata/historical engagement → urgency (low/med/high). Train and compare 2 models, report honest metrics (precision/recall, not just accuracy)
- [ ] **Send-time optimizer**: predict best send hour per user from simulated engagement patterns
- [ ] **Channel preference predictor** (once the above two are solid)
- [ ] Shared Feature Builder used by both training and inference to prevent training-serving skew
- [ ] Stateless online inference module invoked through the in-process ML Engine boundary at API intake; log model version + prediction + confidence per notification (this becomes explainability data)
- [ ] Offline training pipeline separated from online inference path: Training Data Source, Dataset Builder, Model Trainer, evaluator, and explicit promotion step
- [ ] Model Registry loads promoted model versions from S3/MinIO-compatible object storage and supports rollback
- [ ] Engagement Tracker consumes validated provider engagement events and feeds the training data source without mixing synthetic and real data in one training run
- [ ] Tests asserting model performance stays above a floor threshold

**Exit criteria:** Every notification entering the pipeline gets a priority score and a suggested send time, traceable to a specific model version and feature set; candidate models are evaluated, stored, and promoted deliberately before serving.

### Phase 6: AI / LLM Services

- [ ] Provider-agnostic prompt interface (supports swapping Groq/Gemini/others without touching call sites)
- [ ] AI Gateway remains an in-process boundary and degrades to original content if unavailable
- [ ] Summarization
- [ ] Tone adaptation
- [ ] Subject generation (cheap to add once the interface exists)
- [ ] Translation and digest creation as documented enhancement paths after summarization/tone/subject generation are stable
- [ ] Clear separation maintained: LLM touches _content_, ML models touch _routing/timing/priority_
- [ ] Graceful degradation: pipeline still functions if the AI service is unavailable (per the vision's "AI as enhancement" principle)

**Exit criteria:** Full pipeline runs end-to-end: notification in → priority assigned → send-time scheduled → content enhanced → delivered, and still works with the AI layer disabled.

### Phase 7: Platform Features and Frontend

- [ ] Project management as the active tenancy boundary; Workspace remains explicitly future scope
- [ ] User preferences (channel opt-in/out, quiet hours, delivery windows, timezone, channel priorities)
- [ ] Delivery policy management for project-level blackout dates and compliance restrictions
- [ ] Auth (API key or JWT): signature validation first, Redis revocation/blocklist check second, fail closed with 503 when Redis is unavailable
- [ ] API key lifecycle management with revocation dual-written to Postgres and Redis from the caller's perspective
- [ ] Next.js dashboard: notification feed with status/channel/priority, "trigger test notification" form
- [ ] Explainability panel: "why was this flagged high priority," showing the feature trace
- [ ] Simulated data viewer: charts of synthetic engagement (sells the simulator work visually)
- [ ] Minimal operational view (provider health, queue depth, DLQ count, Redis/RabbitMQ health) — full audit logs/analytics deferred

**Exit criteria:** A non-technical person can open the dashboard, trigger a notification, and understand what the system decided and why.

### Phase 8: Observability

- [ ] Structured JSON logging across API and workers
- [ ] `/metrics` endpoint (Prometheus format): queue depth, DLQ count, delivery success rate, retry count, model latency, AI degradation count
- [ ] OTLP export for inference calls and training runs: model version, prediction, confidence, latency, and evaluation metrics
- [ ] Correlation IDs propagate through API, RabbitMQ payloads, worker logs, delivery attempts, webhooks, ML prediction logs, and AI enhancement logs
- [ ] Security pass: no raw SQL, secrets in env vars, CORS configured properly
- [ ] Load test with Locust to get real numbers for the README
- [ ] Test coverage review on critical paths

### Phase 9: Deployment, Docs, Demo

- [ ] Deploy backend + worker + Postgres to Render/Fly.io
- [ ] Provision RabbitMQ via CloudAMQP free tier (or paid PaaS tier) and a Redis instance for auth state, rate limiting, and idempotency
- [ ] Provision S3-compatible object storage for model artefacts and training datasets
- [ ] Deploy frontend to Vercel, wired to live backend
- [ ] Final README: architecture diagram, ADRs, model metrics with honest numbers (including weaknesses), "what's deferred to V2 and why," "what I'd change at 10x scale"
- [ ] Tag a `v0.9.0` release candidate; tag `v1.0.0` only after the production acceptance checklist is green

### Phase 10+: Toward Full Vision

- [ ] Promote SMS/webhook/in-app adapters from mock to live providers
- [ ] Full audit logging and analytics
- [ ] Distributed tracing
- [ ] Translation and digest creation
- [ ] A/B testing for notification strategies, multi-region, tenant-specific models
- [ ] Developer Experience (SDKs, CLIs, etc)
