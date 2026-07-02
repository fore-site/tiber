# System Context Diagram

**C4 Level:** 1. System Context
**Container in focus:** N/A

---

## Purpose

This diagram defines Tiber's system boundary and identifies every external actor and system it interacts with. It is intended for any reader be it technical or non-technical, who needs to understand what Tiber is, who uses it, and what it depends on before reading any further architecture detail. It deliberately omits internal structure; that is the concern of the Level 2 Container diagram.

---

## Diagram

![context diagram](../diagrams/context-diagram.svg)

---

## Key Decisions

- **End User is an external actor, not a Tiber user:** End users receive notifications but never interact with Tiber directly. They are customers of the client application, not of Tiber. This distinction matters for the data model, Tiber holds a recipient identifier (email, device token) but does not own the user relationship.

- **AI Providers and Notification Providers are intentionally separate external systems:** AI providers enhance notification content before dispatch; notification providers handle physical delivery after dispatch. Keeping them as distinct external dependencies means either can be swapped, degraded, or mocked independently without affecting the other.

- **Client Applications interact with Tiber only via the REST API:** There is no SDK, no direct database access, and no message queue integration for external clients in this version. This is a deliberate boundary, it keeps the API as the single integration surface and makes versioning, auth enforcement, and rate limiting straightforward.

- **Monitoring Systems have a bidirectional relationship:** Tiber exposes metrics and health endpoints; monitoring systems scrape them. Tiber does not push metrics to an external system. This is a pull-based observability model appropriate for the deployment targets.

---

## What This Diagram Does Not Show

This diagram does not show how Tiber works internally. It shows only what interacts with it and how. Internal containers (API service, worker, message broker, databases) are detailed in the Level 2 Container diagram. Delivery channels, provider failover logic, and AI service integration are not visible at this level by design; the C4 model surfaces those concerns progressively in lower-level diagrams.
