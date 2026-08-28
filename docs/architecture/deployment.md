# Deployment Architecture

## Purpose

This document defines the local deployment architecture for Tiber during early development.

The goal is **not** to deploy a production system. Instead, it provides a reproducible development environment that mirrors the core infrastructure Tiber depends on while keeping application development independent.

The deployment is intentionally minimal. Infrastructure services are provisioned first, while the API Service and Worker Service are added once executable application code exists.

---

# Objectives

The local deployment environment must:

* provide all infrastructure required by the application
* require only Docker Compose to start
* isolate services on a dedicated Docker network
* persist state where appropriate
* allow developers to connect directly to each service
* closely resemble the production topology without unnecessary complexity

---

# Scope

Included:

* PostgreSQL
* Redis
* RabbitMQ
* MinIO

Deferred until implementation exists:

* API Service
* Worker Service
* Reverse proxy
* Monitoring stack
* ML serving infrastructure

---

# Deployment Topology

```
                    ┌────────────────────────────┐
                    │       Docker Network       │
                    │          tiber             │
                    └─────────────┬──────────────┘
                                  │
          ┌──────────────┬────────┼───────────┬──────────────┐
          │              │        │           │              │
          ▼              ▼        ▼           ▼              ▼
     PostgreSQL       Redis   RabbitMQ     MinIO        (future)
                                                    API / Worker
```

All services communicate using Docker service names.

No container communicates with another container using `localhost`.

---

# Infrastructure Services

## PostgreSQL

### Purpose

Primary relational database.

Stores:

* users
* projects
* notifications
* templates
* recipients
* ML metadata
* delivery history
* audit information

### Persistence

Persistent Docker volume.

No data should be lost between container restarts.

### Access

Internal hostname:

```
postgres
```

Default port:

```
5432
```

---

## Redis

### Purpose

High-speed transient storage.

Used for:

* JWT blocklist
* API key authentication cache
* idempotency cache

Redis is **not** a source of truth.

Every cached object can be reconstructed from PostgreSQL.

### Persistence

None.

Redis may be emptied at any time.

### Access

Internal hostname:

```
redis
```

Port:

```
6379
```

---

## RabbitMQ

### Purpose

Message broker connecting the API Service and Worker Service.

Responsibilities include:

* notification dispatch jobs
* webhook delivery jobs
* ML inference requests
* engagement event publishing

### Persistence

Persistent Docker volume.

### Management UI

Enabled during development.

Default UI:

```
http://localhost:15672
```

### Access

Internal hostname:

```
rabbitmq
```

AMQP:

```
5672
```

---

## MinIO

### Purpose

Local object storage compatible with the S3 API.

Stores:

* trained ML models
* materialised datasets
* exported reports
* future binary artifacts

### Persistence

Persistent Docker volume.

### Initial Bucket

```
tiber-artifacts
```

### Access

Internal hostname:

```
minio
```

API:

```
9000
```

Console:

```
9001
```

---

# Docker Network

A single bridge network is used.

```
tiber
```

Every container joins this network.

No service should expose internal hostnames or IP addresses.

Communication occurs through Docker DNS.

Example:

```
postgres
redis
rabbitmq
minio
```

---

# Persistent Volumes

The following Docker volumes are created.

| Volume        | Purpose                              |
| ------------- | ------------------------------------ |
| postgres_data | PostgreSQL database files            |
| rabbitmq_data | RabbitMQ durable queues and metadata |
| minio_data    | Object storage                       |

Redis intentionally has no persistent volume.

---

# Health Checks

Every infrastructure service exposes a health check.

## PostgreSQL

```
pg_isready
```

---

## Redis

```
redis-cli ping
```

---

## RabbitMQ

```
rabbitmq-diagnostics ping
```

---

## MinIO

```
mc ready
```

Containers depending on these services should wait for healthy status before starting.

---

# Environment Variables

Application containers will consume configuration from a shared `.env` file.

Expected variables include:

```
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

REDIS_HOST=redis
REDIS_PORT=6379

RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672

MINIO_ENDPOINT=minio:9000
MINIO_BUCKET=tiber-artifacts
```

Secrets are never committed to source control.

Only `.env.example` is tracked.

---

# Startup Order

Infrastructure starts in the following order.

1. PostgreSQL
2. Redis
3. RabbitMQ
4. MinIO

Future application services should wait until all required dependencies report healthy status.

---

# Application Services (Future)

## API Service

Will be added after the initial FastAPI implementation exists.

Responsibilities:

* REST API
* authentication
* scheduling
* policy resolution
* job publishing

The API Service will communicate with:

* PostgreSQL
* Redis
* RabbitMQ
* MinIO

---

## Worker Service

Will be added after the Celery worker implementation exists.

Responsibilities:

* consume RabbitMQ jobs
* dispatch notifications
* send webhooks
* coordinate ML inference
* record delivery attempts

The Worker Service will communicate with:

* RabbitMQ
* PostgreSQL
* Redis
* MinIO

---

# Design Decisions

## Infrastructure First

Infrastructure is provisioned before application containers.

This allows each service to be developed independently while relying on stable local dependencies.

---

## Single Docker Network

All services communicate through Docker DNS rather than host networking.

This mirrors production deployments and avoids hardcoded addresses.

---

## Redis Without Persistence

Redis functions exclusively as a cache.

Loss of cached data should never affect correctness.

Application services rebuild cache entries on demand using PostgreSQL.

---

## Local Object Storage

MinIO is used instead of AWS S3 during development.

Because MinIO implements the S3 API, production migration requires only configuration changes rather than application code changes.

---

## Deferred Application Containers

The API Service and Worker Service are intentionally excluded from the initial Docker Compose stack because executable application code does not yet exist.

They will be introduced once the FastAPI application and Celery worker have been implemented.

This keeps the deployment environment aligned with the current maturity of the project and avoids maintaining placeholder containers.

---

# Phase 1 Deliverable

At the completion of this phase, running:

```
docker compose up
```

will provision a fully operational local infrastructure consisting of:

* PostgreSQL
* Redis
* RabbitMQ
* MinIO

This environment forms the foundation upon which the API Service and Worker Service will be developed in subsequent phases.
