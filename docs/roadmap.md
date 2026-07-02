# Tiber Project Roadmap

**An AI/ML-augmented production-grade notification platform**
Stack: FastAPI + Celery + Postgres + scikit-learn + Next.js

---

## Release Plan

Each release corresponds to a completed roadmap phase. Releases are cumulative, meaning each version includes all functionality from previous versions.

| Version | Phase                                   | Status     |
| ------- | --------------------------------------- | ---------- |
| v0.1.0  | Phase 1: Foundations and System Design  | ⏳ Planned |
| v0.2.0  | Phase 2: Core Notification Engine       | ⏳ Planned |
| v0.3.0  | Phase 3: Provider Abstraction           | ⏳ Planned |
| v0.4.0  | Phase 4: Data Simulator                 | ⏳ Planned |
| v0.5.0  | Phase 5: Machine Learning Services      | ⏳ Planned |
| v0.6.0  | Phase 6: AI/LLM Services                | ⏳ Planned |
| v0.7.0  | Phase 7: Platform Features and Frontend | ⏳ Planned |
| v0.8.0  | Phase 8: Observability                  | ⏳ Planned |
| v1.0.0  | Production Release                      | ⏳ Planned |

### Release History

This section becomes a historical log as the project evolves.

| Version | Date | Highlights      |
| ------- | ---- | --------------- |
| —       | —    | No releases yet |

---

## Roadmap

### Phase 1: Foundations and System Design

- [ ] Repo scaffold (monorepo: `/backend`, `/frontend`, `/docs`)
- [ ] Architecture doc + diagram (this doc is the seed)
- [ ] API contract first (OpenAPI spec — design before you build)
- [ ] DB schema design: `users`, `notifications`, `delivery_logs`, `events`, `preferences`, `providers`
- [ ] Docker Compose: API + Postgres + RabbitMQ + Redis, running locally
- [ ] GitHub Actions skeleton: lint (ruff) + test (pytest) on push
- [ ] ADRs: "Why Celery over FastAPI BackgroundTasks," "Why RabbitMQ over Redis as broker (learning-driven, exchanges/routing keys vs. simple list queue)," "Why provider abstraction over direct integration," "AI vs. ML boundary definition"

**Exit criteria:** `docker-compose up` gives a running API with `/health`, a real schema, CI green on an empty test suite.

### Phase 2: Core Notification Engine

- [ ] `POST /notifications` : validate, persist, enqueue (idempotency key required)
- [ ] Celery worker: retry with exponential backoff, dead-letter queue after N failures
- [ ] Scheduling support (send-at-time, not just immediate)
- [ ] Rate limiting on ingestion
- [ ] Template rendering (basic; variables into a message body)
- [ ] Delivery status tracking + logs
- [ ] Unit tests for business logic, integration tests for the full enqueue→deliver flow

**Exit criteria:** A notification can be created, scheduled, and tracked through pending → processing → delivered/failed, with retries visible in logs.

### Phase 3: Provider Abstraction and Multi-Channel Delivery

- [ ] Define a `ChannelProvider` interface (send, health-check, capabilities)
- [ ] Email adapter : live integration (SendGrid or Resend)
- [ ] Push adapter : live integration (FCM)
- [ ] SMS, webhook, in-app adapters : built against the same interface, using mock/sandbox implementations, clearly documented as drop-in-ready
- [ ] Failover logic: if primary provider fails health check or delivery, fall back to secondary (can be demonstrated with email primary + a second email provider, or live/mock pairing)
- [ ] Provider health monitoring (simple periodic check + status table)

**Exit criteria:** The same notification can route through any of the 5 channels via one interface; failover is demonstrable end-to-end on at least one channel.

### Phase 4: Data Simulator

- [ ] Design 4-6 synthetic user personas (e.g. "early-bird email opener," "ignores SMS," "high engagement on push between 6-9pm")
- [ ] Simulator module generating users, notification history, and engagement events (opened/clicked/ignored) with configurable noise
- [ ] `is_synthetic` flag so demo data and training data are never confused with real data
- [ ] Document the simulator's assumptions and design in its own README section
- [ ] Generate and sanity-check a first training dataset (plot it, don't just trust it)

**Exit criteria:** `python -m simulator generate --users 500 --days 90` produces a realistic, inspectable dataset you'd be comfortable explaining feature-by-feature in an interview.

### Phase 5: Machine Learning Services

- [ ] **Priority classifier**: feature engineering from content/metadata/historical engagement → urgency (low/med/high). Train and compare 2 models, report honest metrics (precision/recall, not just accuracy)
- [ ] **Send-time optimizer**: predict best send hour per user from simulated engagement patterns
- [ ] **Channel preference predictor** (once the above two are solid)
- [ ] Inference module called at enqueue time; log model version + prediction + confidence per notification (this becomes explainability data)
- [ ] Offline training pipeline separated from online inference path
- [ ] Tests asserting model performance stays above a floor threshold

**Exit criteria:** Every notification entering the pipeline gets a priority score and a suggested send time, traceable to a specific model version and feature set.

### Phase 6: AI / LLM Services

- [ ] Provider-agnostic prompt interface (supports swapping Groq/Gemini/others without touching call sites)
- [ ] Summarization
- [ ] Tone adaptation
- [ ] Subject generation (cheap to add once the interface exists)
- [ ] Translation and digest creation; later additions once the core is stable
- [ ] Clear separation maintained: LLM touches _content_, ML models touch _routing/timing/priority_
- [ ] Graceful degradation: pipeline still functions if the AI service is unavailable (per the vision's "AI as enhancement" principle)

**Exit criteria:** Full pipeline runs end-to-end: notification in → priority assigned → send-time scheduled → content enhanced → delivered, and still works with the AI layer disabled.

### Phase 7: Platform Features and Frontend

- [ ] User preferences (channel opt-in/out, quiet hours)
- [ ] Auth (API key or JWT)
- [ ] Next.js dashboard: notification feed with status/channel/priority, "trigger test notification" form
- [ ] Explainability panel: "why was this flagged high priority," showing the feature trace
- [ ] Simulated data viewer: charts of synthetic engagement (sells the simulator work visually)
- [ ] Minimal operational view (provider health, queue depth) — full audit logs/analytics deferred

**Exit criteria:** A non-technical person can open the dashboard, trigger a notification, and understand what the system decided and why.

### Phase 8: Observability

- [ ] Structured JSON logging across API and workers
- [ ] `/metrics` endpoint (Prometheus format); Queue depth, delivery success rate, model latency
- [ ] Security pass: no raw SQL, secrets in env vars, CORS configured properly
- [ ] Load test with Locust to get real numbers for the README
- [ ] Test coverage review on critical paths

### Phase 9: Deployment, Docs, Demo

- [ ] Deploy backend + worker + Postgres to Render/Fly.io
- [ ] Provision RabbitMQ via CloudAMQP free tier (or paid PaaS tier) and a small Redis instance for rate limiting
- [ ] Deploy frontend to Vercel, wired to live backend
- [ ] Final README: architecture diagram, ADRs, model metrics with honest numbers (including weaknesses), "what's deferred to V2 and why," "what I'd change at 10x scale"
- [ ] Tag a `v1.0` release

### Phase 10+: Toward Full Vision

- [ ] Promote SMS/webhook/in-app adapters from mock to live providers
- [ ] Full audit logging and analytics
- [ ] Distributed tracing
- [ ] Translation and digest creation
- [ ] A/B testing for notification strategies, multi-region, tenant-specific models
- [ ] Developer Experience (SDKs, CLIs, etc)

---
