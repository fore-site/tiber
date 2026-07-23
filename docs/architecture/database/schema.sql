-- Tiber Database Schema
-- Version: 0.1.0
-- PostgreSQL 16+

-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "citext";    -- case-insensitive text for emails

-- Enums

CREATE TYPE delivery_channel AS ENUM (
    'email',
    'push',
    'sms',
    'webhook',
    'in_app'
);

CREATE TYPE user_role AS ENUM (
    'admin',
    'user'
);

CREATE TYPE notification_status AS ENUM (
    'pending',
    'scheduled',
    'processing',
    'delivered',
    'failed',
    'policy_rejected',
    'cancelled'
);

CREATE TYPE delivery_attempt_status AS ENUM (
    'succeeded',
    'failed'
);

CREATE TYPE webhook_event_status AS ENUM (
    'delivered',
    'failed'
);

CREATE TYPE engagement_event_type AS ENUM (
    'open',
    'click',
    'bounce',
    'complaint',
    'unsubscribe'
);

CREATE TYPE send_time_basis AS ENUM (
    'explicit',
    'ml_predicted',
    'immediate'
);

CREATE TYPE ml_priority AS ENUM (
    'low',
    'medium',
    'high'
);

CREATE TYPE ml_model_type AS ENUM (
    'priority_classifier',
    'send_time_predictor',
    'channel_preference_predictor'
);

CREATE TYPE ml_model_status AS ENUM (
    'candidate',
    'active',
    'retired'
);

CREATE TYPE training_run_status AS ENUM (
    'running',
    'completed',
    'failed'
);

CREATE TYPE auth_token_type AS ENUM (
    'email_verification',
    'password_reset'
);

CREATE TYPE webhook_event_type AS ENUM (
    'notification.delivered',
    'notification.failed',
    'notification.cancelled',
    'notification.policy_rejected'
);

-- Users

CREATE TABLE users (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email         CITEXT      NOT NULL,
    password_hash TEXT        NULL,
    role          user_role   NOT NULL DEFAULT 'user',
    is_verified   BOOLEAN     NOT NULL DEFAULT FALSE,
    pending_email CITEXT      NULL,
    github_id     VARCHAR(50) NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT users_email_unique     UNIQUE (email),
    CONSTRAINT users_github_id_unique UNIQUE (github_id)
);

COMMENT ON TABLE  users               IS 'Platform users — developers and administrators. Global role applies across the entire platform.';
COMMENT ON COLUMN users.password_hash IS 'argon2 hash. NULL for accounts created via GitHub OAuth.';
COMMENT ON COLUMN users.is_verified   IS 'Whether the email address has been confirmed. Always TRUE for GitHub OAuth accounts.';
COMMENT ON COLUMN users.pending_email IS 'New email awaiting verification after PATCH /v1/auth/me. Promoted to active email once verified.';
COMMENT ON COLUMN users.github_id     IS 'GitHub user ID for OAuth accounts. NULL for email/password accounts.';

-- Auth Tokens
-- Short-lived tokens for email verification and password reset
-- Tokens are hashed before storage. Raw values are sent to users via email only.

CREATE TABLE auth_tokens (
    id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID         NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash CHAR(64)  NOT NULL,
    token_type auth_token_type  NOT NULL,
    expires_at TIMESTAMPTZ  NOT NULL,
    used_at    TIMESTAMPTZ  NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT auth_tokens_token_hash_unique UNIQUE (token_hash)
);

COMMENT ON TABLE  auth_tokens            IS 'Short-lived hashed tokens for email verification, and password reset flows.';
COMMENT ON COLUMN auth_tokens.token_hash IS 'SHA-256 hex hash of the raw token. The raw token is sent to the user via email and never stored.';
COMMENT ON COLUMN auth_tokens.token_type IS 'Discriminator: email_verification | password_reset.';
COMMENT ON COLUMN auth_tokens.used_at    IS 'Set when the token is consumed. Used tokens cannot be reused regardless of expiry.';

-- Projects
-- Primary tenancy boundary. All resources belong to exactly one project.

CREATE TABLE projects (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID         NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    name        VARCHAR(100) NOT NULL,
    slug        VARCHAR(100) NOT NULL,
    description TEXT         NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    archived_at TIMESTAMPTZ  NULL,

    CONSTRAINT projects_user_slug_unique UNIQUE (user_id, slug)
);

COMMENT ON TABLE  projects IS 'Primary tenancy boundary. Every API key, template, recipient, notification, webhook, and delivery policy belongs to exactly one project.';
COMMENT ON COLUMN projects.slug IS 'Human-readable label for the owner''s own reference. Unique per user, not globally. Never used in public URLs — all API paths use the UUID primary key.';
COMMENT ON COLUMN projects.user_id IS 'Owning user. Project ownership cannot be transferred in the current model.';
COMMENT ON COLUMN projects.archived_at IS 'Soft delete. Non-null means the project is archived. Archived projects are excluded from normal API operations but retained for historical and audit purposes.';

-- API Keys

CREATE TABLE api_keys (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   UUID         NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    name         VARCHAR(100) NOT NULL,
    key_hash     CHAR(64)  NOT NULL,
    key_prefix   VARCHAR(20)  NOT NULL,
    last_used_at TIMESTAMPTZ  NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    revoked_at   TIMESTAMPTZ  NULL,
    expires_at TIMESTAMPTZ    NULL,

    CONSTRAINT api_keys_key_hash_unique UNIQUE (key_hash)
);

COMMENT ON TABLE  api_keys            IS 'Project-scoped machine authentication keys. The raw key is shown once on creation and never stored.';
COMMENT ON COLUMN api_keys.key_hash   IS 'SHA-256 hex hash of the raw tb_xxxxx key.';
COMMENT ON COLUMN api_keys.key_prefix IS 'First characters of the key for display in the UI. Never the full key.';
COMMENT ON COLUMN api_keys.revoked_at IS 'Soft delete via revocation. Non-null means the key is permanently revoked and rejected during authentication.';

-- Templates

CREATE TABLE templates (
    id         UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID             NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    name       VARCHAR(100)     NOT NULL,
    slug       VARCHAR(100)     NOT NULL,
    channel    delivery_channel NOT NULL,
    subject    TEXT             NULL,
    body       TEXT             NOT NULL,
    created_at TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

    CONSTRAINT templates_project_slug_unique UNIQUE (project_id, slug),

    CONSTRAINT templates_name_unique UNIQUE (project_id, name),
    
    CONSTRAINT templates_subject_check CHECK (
        (channel = 'email' AND subject IS NOT NULL)
        OR
        (channel <> 'email' AND subject IS NULL)
        )
);

COMMENT ON TABLE  templates         IS 'Reusable notification content templates with {{variable}} interpolation, scoped per project.';
COMMENT ON COLUMN templates.slug    IS 'URL-safe identifier, unique within a project. Immutable after creation.';
COMMENT ON COLUMN templates.subject IS 'Subject line template. NULL for channels without a subject (push, SMS, in_app). Supports {{variable}} interpolation.';
COMMENT ON COLUMN templates.body    IS 'Body template. Supports {{variable}} interpolation.';

-- Recipients

CREATE TABLE recipients (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   UUID         NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    external_id  VARCHAR(255) NULL,
    addresses JSONB NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    archived_at  TIMESTAMPTZ  NULL,

    CONSTRAINT recipients_project_external_id_unique
        UNIQUE (project_id, external_id),

    CONSTRAINT recipients_address_type_check CHECK (jsonb_typeof(addresses) = 'object'),
    
    CONSTRAINT recipients_addresses_not_empty CHECK (addresses != '{}'::jsonb)
);

COMMENT ON TABLE  recipients             IS 'Notification recipients. Encapsulates channel-specific addressing information.';
COMMENT ON COLUMN recipients.external_id IS 'Caller''s stable identifier for this recipient. Optional but recommended for idempotent recipient management.';
COMMENT ON COLUMN recipients.addresses IS 'Channel-specific delivery addresses for the recipient. Keys correspond to supported delivery channels (email, sms, push, webhook, etc.).';
COMMENT ON COLUMN recipients.archived_at IS 'Soft delete. Archived recipients cannot receive new notifications.';

-- User Preferences
-- Singleton per recipient.

CREATE TABLE user_preferences (
    id                    UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_id          UUID              NOT NULL REFERENCES recipients (id) ON DELETE CASCADE,
    project_id            UUID              NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    preferred_channels    delivery_channel[] NULL,
    opted_out_channels    delivery_channel[] NULL,
    quiet_hours_start     TIME               NULL,
    quiet_hours_end       TIME               NULL,
    delivery_window_start TIME               NULL,
    delivery_window_end   TIME               NULL,
    timezone              VARCHAR(100)       NOT NULL DEFAULT 'UTC',
    updated_at            TIMESTAMPTZ        NOT NULL DEFAULT NOW(),

    CONSTRAINT user_preferences_recipient_unique UNIQUE (recipient_id),

    CONSTRAINT user_preferences_quiet_hours_check
        CHECK (
            (quiet_hours_start IS NULL AND quiet_hours_end IS NULL)
            OR (quiet_hours_start IS NOT NULL AND quiet_hours_end IS NOT NULL)
        ),

    CONSTRAINT user_preferences_delivery_window_check
        CHECK (
            (delivery_window_start IS NULL AND delivery_window_end IS NULL)
            OR (delivery_window_start IS NOT NULL AND delivery_window_end IS NOT NULL)
        )
);

COMMENT ON TABLE  user_preferences                      IS 'Recipient-level delivery preferences. Singleton per recipient. Evaluated by the Delivery Policy Resolver at notification intake.';
COMMENT ON COLUMN user_preferences.preferred_channels   IS 'Ordered channel preference. First channel is tried first.';
COMMENT ON COLUMN user_preferences.opted_out_channels   IS 'Channels this recipient has opted out of. Notifications targeting these channels are rejected at intake.';
COMMENT ON COLUMN user_preferences.quiet_hours_start    IS 'Start of quiet hours in the recipient''s timezone. Notifications during quiet hours are rescheduled, not dropped.';
COMMENT ON COLUMN user_preferences.timezone             IS 'IANA timezone identifier used for quiet hours and delivery window evaluation.';

-- Notifications
-- Immutable after acceptance. Status is the only mutable field post-creation.
-- Notifications cannot be deleted.

CREATE TABLE notifications (
    id                UUID                NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        UUID                NOT NULL REFERENCES projects (id) ON DELETE RESTRICT,
    recipient_id      UUID                NOT NULL REFERENCES recipients (id) ON DELETE RESTRICT,
    template_id       UUID                NULL REFERENCES templates (id) ON DELETE SET NULL,
    channel           delivery_channel    NOT NULL,
    status            notification_status NOT NULL DEFAULT 'pending',
    idempotency_key   VARCHAR(255)        NULL,
    correlation_id    UUID                NOT NULL,
    subject           TEXT                NULL,
    body              TEXT                NOT NULL,
    template_variables JSONB              NULL,
    scheduled_at      TIMESTAMPTZ         NULL,
    send_time_basis   send_time_basis     NOT NULL DEFAULT 'immediate',
    policy_violation_reason TEXT          NULL,
    delivered_at      TIMESTAMPTZ         NULL,
    created_at        TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ         NOT NULL DEFAULT NOW(),

    CONSTRAINT notifications_project_idempotency_key_unique
        UNIQUE (project_id, idempotency_key),

    CONSTRAINT notifications_template_variables_check CHECK (
            template_variables IS NULL
            OR jsonb_typeof(template_variables) = 'object'
        ),

    CONSTRAINT notifications_policy_violation_check CHECK (
            (
                status = 'policy_rejected'
                AND policy_violation_reason IS NOT NULL
            )
            OR
            (
                status <> 'policy_rejected'
                AND policy_violation_reason IS NULL
            )
        ),
    
    CONSTRAINT notifications_subject_check CHECK (
        (channel = 'email' AND subject IS NOT NULL)
            OR
        (channel <> 'email' AND subject IS NULL)
        )
);

COMMENT ON TABLE  notifications                   IS 'Notification requests accepted by Tiber. Immutable after acceptance — retries produce new delivery_attempts, not new notifications. Cannot be deleted.';
COMMENT ON COLUMN notifications.correlation_id    IS 'Trace ID propagated through all pipeline logs, the job payload, delivery attempts, webhook events, and ML prediction logs.';
COMMENT ON COLUMN notifications.idempotency_key   IS 'Client-supplied deduplication key. Duplicate submissions with the same key within 24 hours return the original response.';
COMMENT ON COLUMN notifications.body              IS 'Rendered body after template interpolation. Stored pre-rendered so delivery always uses a stable snapshot.';
COMMENT ON COLUMN notifications.template_variables IS 'Variables supplied by the caller for template interpolation. Stored for auditability.';
COMMENT ON COLUMN notifications.send_time_basis   IS 'How scheduled_at was determined: explicit (caller-provided), ml_predicted, or immediate.';
COMMENT ON COLUMN notifications.policy_violation_reason IS 'Populated when status is policy_rejected. Records which policy was violated and why.';

-- Notification Intelligence
-- ML predictions attached at intake. Stored separately to keep the notifications
-- table lean and to make ML concerns clearly separated from delivery concerns.

CREATE TABLE notification_intelligence (
    notification_id                  UUID             PRIMARY KEY REFERENCES notifications (id) ON DELETE CASCADE,
    priority                         ml_priority      NULL,
    channel_preference               delivery_channel NULL,
    priority_confidence              DECIMAL(4, 3)    NULL,
    send_time_confidence             DECIMAL(4, 3)    NULL,
    channel_preference_confidence    DECIMAL(4, 3)    NULL,
    priority_model_version           VARCHAR(100)     NULL,
    send_time_model_version          VARCHAR(100)     NULL,
    channel_preference_model_version VARCHAR(100)     NULL,
    created_at                       TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

    CONSTRAINT notification_intelligence_priority_confidence_check CHECK (
        priority_confidence IS NULL
        OR priority_confidence BETWEEN 0 AND 1
    ),

    CONSTRAINT notification_intelligence_send_time_confidence_check CHECK (
        send_time_confidence IS NULL
        OR send_time_confidence BETWEEN 0 AND 1
    ),

    CONSTRAINT notification_intelligence_channel_preference_confidence_check CHECK (
        channel_preference_confidence IS NULL
        OR channel_preference_confidence BETWEEN 0 AND 1
    )
);

COMMENT ON TABLE  notification_intelligence                       IS 'ML predictions attached at API Service intake. 1:1 with notifications. NULL columns indicate the ML Engine was unavailable and defaults were applied.';
COMMENT ON COLUMN notification_intelligence.priority_confidence   IS 'Model confidence between 0 and 1. Exposed via the explainability panel in the dashboard.';
COMMENT ON COLUMN notification_intelligence.priority_model_version IS 'References model_versions.version. Enables tracing a prediction back to a specific trained artifact.';

-- Delivery Attempts
-- Append-only. One row per attempt. Never updated or deleted.

CREATE TABLE delivery_attempts (
    id                      UUID                    PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id         UUID                    NOT NULL REFERENCES notifications (id) ON DELETE RESTRICT,
    attempt_number          SMALLINT                NOT NULL,
    status                  delivery_attempt_status NOT NULL,
    channel                 delivery_channel        NOT NULL,
    provider                VARCHAR(100)            NOT NULL,
    provider_message_id     VARCHAR(255)            NULL,
    error                   TEXT                    NULL,
    created_at              TIMESTAMPTZ             NOT NULL DEFAULT NOW(),

    CONSTRAINT delivery_attempts_notification_attempt_unique
        UNIQUE (notification_id, attempt_number),

    CONSTRAINT delivery_attempts_attempt_number_check CHECK (attempt_number > 0)
);

COMMENT ON TABLE  delivery_attempts                     IS 'Immutable record of each delivery attempt. Never updated or deleted.';
COMMENT ON COLUMN delivery_attempts.provider_message_id IS 'The provider''s own reference ID (e.g. Resend''s email_id). Used to correlate inbound provider engagement webhooks back to a specific attempt.';

-- Providers
-- Persisted record of configured external delivery services and health state.
-- Distinct from infrastructure/providers/ adapters which are the code that calls them.

CREATE TABLE providers (
    id              UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(100)     NOT NULL,
    channel         delivery_channel NOT NULL,
    is_active       BOOLEAN          NOT NULL DEFAULT TRUE,
    is_healthy      BOOLEAN          NOT NULL DEFAULT TRUE,
    last_checked_at TIMESTAMPTZ      NULL,
    configuration   JSONB            NULL,
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

    CONSTRAINT providers_name_channel_unique UNIQUE (name, channel),

    CONSTRAINT providers_configuration_check CHECK (
            configuration IS NULL
            OR jsonb_typeof(configuration) = 'object'
        )
);

COMMENT ON TABLE  providers               IS 'Configured external delivery services. Tracks health state for failover decisions by the Provider Manager.';
COMMENT ON COLUMN providers.configuration IS 'Provider-specific configuration. Must be encrypted at the application layer before storage — never store plaintext credentials.';
COMMENT ON COLUMN providers.is_healthy    IS 'Updated by the periodic health monitor. Used by the Provider Manager to select healthy adapters for delivery.';

-- Webhook Endpoints
-- Client-registered outbound callback destinations.
-- API Service owns registration. Worker Service owns firing.

CREATE TABLE webhook_endpoints (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    url        TEXT        NOT NULL,
    events     webhook_event_type[]      NOT NULL,
    encrypted_signing_secret TEXT NOT NULL,
    secret_prefix            VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT webhook_endpoints_project_url_unique UNIQUE(project_id, url),

    CONSTRAINT webhook_endpoints_events_not_empty CHECK (cardinality(events) > 0)
);

COMMENT ON TABLE  webhook_endpoints        IS 'Client-registered endpoints that Tiber calls on notification lifecycle events. The API Service owns registration; the Worker Service owns firing.';
COMMENT ON COLUMN webhook_endpoints.events IS 'Subscribed event types: notification.delivered, notification.failed, notification.cancelled, notification.policy_rejected.';
COMMENT ON COLUMN webhook_endpoints.encrypted_signing_secret IS 'Encrypted webhook signing secret used to compute HMAC signatures for outbound webhook requests. The plaintext secret is returned only once during endpoint creation';
COMMENT ON COLUMN webhook_endpoints.secret_prefix IS 'First characters of the signing secret displayed in the dashboard to identify the active secret without revealing it.';

-- Webhook Events
-- Delivery record of each outbound webhook callback attempt.

CREATE TABLE webhook_events (
    id                   UUID                 PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id          UUID                 NOT NULL REFERENCES webhook_endpoints (id) ON DELETE CASCADE,
    notification_id      UUID                 NOT NULL REFERENCES notifications (id) ON DELETE RESTRICT,
    event_type webhook_event_type             NOT NULL,
    status               webhook_event_status NOT NULL,
    response_status_code SMALLINT             NULL,
    error                TEXT                 NULL,
    attempt_number       SMALLINT             NOT NULL DEFAULT 1,
    created_at           TIMESTAMPTZ          NOT NULL DEFAULT NOW(),

    CONSTRAINT webhook_events_unique_attempt
        UNIQUE (
            endpoint_id,
            notification_id,
            attempt_number
        )
);

COMMENT ON TABLE  webhook_events                     IS 'Delivery record of outbound webhook callbacks. Tracked independently from notification delivery outcomes.';
COMMENT ON COLUMN webhook_events.response_status_code IS 'HTTP status code returned by the client endpoint. NULL if the request could not be made at all.';

-- Delivery Policies
-- Singleton per project. Parent record for blackout_periods and compliance_rules.

CREATE TABLE delivery_policies (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT delivery_policies_project_unique UNIQUE (project_id)
);

COMMENT ON TABLE delivery_policies IS 'Project-level delivery rules. Singleton per project. Parent for blackout_periods and compliance_rules.';

-- Blackout Periods

CREATE TABLE blackout_periods (
    id                 UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    delivery_policy_id UUID         NOT NULL REFERENCES delivery_policies (id) ON DELETE CASCADE,
    name               VARCHAR(255) NOT NULL,
    start_date         DATE         NOT NULL,
    end_date           DATE         NOT NULL,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT blackout_periods_date_order CHECK (end_date >= start_date)
);

COMMENT ON TABLE  blackout_periods           IS 'Calendar periods during which no notifications may be dispatched. Soft constraint — notifications are rescheduled past the blackout, not dropped.';
COMMENT ON COLUMN blackout_periods.start_date IS 'Inclusive start date.';
COMMENT ON COLUMN blackout_periods.end_date   IS 'Inclusive end date.';

-- Compliance Rules

CREATE TABLE compliance_rules (
    id                   UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    delivery_policy_id   UUID              NOT NULL REFERENCES delivery_policies (id) ON DELETE CASCADE,
    name                 VARCHAR(255)      NOT NULL,
    description          TEXT              NULL,
    allowed_window_start TIME              NOT NULL,
    allowed_window_end   TIME              NOT NULL,
    channels             delivery_channel[] NULL,
    created_at           TIMESTAMPTZ       NOT NULL DEFAULT NOW()

);

COMMENT ON TABLE  compliance_rules          IS 'Hard delivery constraints for regulatory compliance. Evaluated after blackout periods. Violations reject the notification — they are never rescheduled.';
COMMENT ON COLUMN compliance_rules.channels IS 'Channels this rule applies to. NULL means the rule applies to all channels.';

-- Engagement Events

CREATE TABLE engagement_events (
    id              UUID                  PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id UUID                  NOT NULL REFERENCES notifications (id) ON DELETE RESTRICT,
    recipient_id    UUID                  NOT NULL REFERENCES recipients (id) ON DELETE RESTRICT,
    project_id      UUID                  NOT NULL REFERENCES projects (id) ON DELETE RESTRICT,
    event_type      engagement_event_type NOT NULL,
    channel         delivery_channel      NOT NULL,
    provider        VARCHAR(100)          NOT NULL,
    occurred_at     TIMESTAMPTZ           NOT NULL,
    is_synthetic    BOOLEAN               NOT NULL DEFAULT FALSE,
    metadata        JSONB                 NULL,
    created_at      TIMESTAMPTZ           NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  engagement_events              IS 'Recipient interactions reported by delivery providers. Primary ML training data source.';
COMMENT ON COLUMN engagement_events.occurred_at  IS 'When the event occurred at the provider — not when Tiber recorded it. The ML Send-Time Predictor trains on this value, not created_at.';
COMMENT ON COLUMN engagement_events.is_synthetic IS 'TRUE for events generated by the data simulator. Excluded from client-facing API responses by default.';
COMMENT ON COLUMN engagement_events.metadata     IS 'Provider-specific event payload.';

-- Engagement Inbound Fallback
-- Safety net for inbound provider engagement webhooks that cannot be published
-- to RabbitMQ. Replayed manually once the broker recovers.

CREATE TABLE engagement_inbound_fallback (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    provider          VARCHAR(100) NOT NULL,
    provider_event_id VARCHAR(255) NOT NULL,
    raw_payload       JSONB        NOT NULL,
    received_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    replayed_at       TIMESTAMPTZ  NULL,

    CONSTRAINT engagement_inbound_fallback_provider_event_unique
        UNIQUE (provider, provider_event_id)
);

COMMENT ON TABLE  engagement_inbound_fallback             IS 'Dead-letter store for inbound provider engagement webhooks that could not be published to RabbitMQ. Replayed manually once the broker recovers.';
COMMENT ON COLUMN engagement_inbound_fallback.replayed_at IS 'Set when this record has been successfully replayed into RabbitMQ. NULL means pending replay.';

-- Training Runs
-- Defined before model_versions because model_versions references it.

CREATE TABLE training_runs (
    id              UUID                PRIMARY KEY DEFAULT gen_random_uuid(),
    model_type      ml_model_type       NOT NULL,
    status          training_run_status NOT NULL DEFAULT 'running',
    dataset_size    INTEGER             NULL,
    synthetic_count INTEGER             NULL,
    real_count      INTEGER             NULL,
    dataset_path    TEXT                NULL,
    error           TEXT                NULL,
    started_at      TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ         NULL,
    created_at      TIMESTAMPTZ         NOT NULL DEFAULT NOW(),

    CONSTRAINT training_runs_dataset_size_check CHECK (
            dataset_size IS NULL
            OR (
                synthetic_count IS NOT NULL
                AND real_count IS NOT NULL
                AND dataset_size = synthetic_count + real_count
            )
        )
);

COMMENT ON TABLE  training_runs               IS 'Record of each offline ML model training run.';
COMMENT ON COLUMN training_runs.dataset_size  IS 'Total number of records in the training dataset.';
COMMENT ON COLUMN training_runs.synthetic_count IS 'Records generated by the data simulator. Tracked separately to prevent unaware mixing of synthetic and real data.';
COMMENT ON COLUMN training_runs.real_count    IS 'Real engagement event records used in training.';
COMMENT ON COLUMN training_runs.dataset_path  IS 'S3/MinIO path to the materialised dataset artifact.';

-- Model Versions

CREATE TABLE model_versions (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    training_run_id UUID            NULL REFERENCES training_runs (id) ON DELETE SET NULL,
    model_type      ml_model_type   NOT NULL,
    version         VARCHAR(100)    NOT NULL,
    artifact_path   TEXT            NOT NULL,
    status          ml_model_status NOT NULL DEFAULT 'candidate',
    precision_score DECIMAL(6, 4)   NULL,
    recall_score    DECIMAL(6, 4)   NULL,
    f1_score        DECIMAL(6, 4)   NULL,
    mae_score       DECIMAL(6, 4)   NULL,
    promoted_at     TIMESTAMPTZ     NULL,
    retired_at      TIMESTAMPTZ     NULL,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT model_versions_version_unique UNIQUE (model_type, version)
);

COMMENT ON TABLE  model_versions               IS 'Trained model artifacts with evaluation metrics and promotion state.';
COMMENT ON COLUMN model_versions.version       IS 'Human-readable version identifier, e.g. priority-2026-01-01.1.';
COMMENT ON COLUMN model_versions.artifact_path IS 'S3/MinIO path to the serialised scikit-learn model artifact.';
COMMENT ON COLUMN model_versions.status        IS 'candidate: trained but not promoted. active: currently serving predictions. retired: superseded by a newer version.';
COMMENT ON COLUMN model_versions.precision_score IS 'For classifiers only (priority, channel preference). NULL for regression models.';
COMMENT ON COLUMN model_versions.mae_score     IS 'Mean Absolute Error. For send_time_predictor only. NULL for classifiers.';
COMMENT ON COLUMN model_versions.promoted_at   IS 'When this version became the active serving model.';
COMMENT ON COLUMN model_versions.retired_at    IS 'When this version was superseded by a newer active version.';

-- Indexes

-- users
CREATE INDEX idx_users_github_id
    ON users (github_id)
    WHERE github_id IS NOT NULL;

-- auth_tokens
CREATE INDEX idx_auth_tokens_user_id
    ON auth_tokens (user_id);
CREATE INDEX idx_auth_tokens_expiry
    ON auth_tokens (expires_at)
    WHERE used_at IS NULL;

-- projects
CREATE INDEX idx_projects_user_id
    ON projects (user_id);
CREATE INDEX idx_projects_active
    ON projects (user_id, created_at DESC)
    WHERE archived_at IS NULL;

-- api_keys
CREATE INDEX idx_api_keys_active
    ON api_keys (project_id)
    WHERE revoked_at IS NULL;

-- templates
CREATE INDEX idx_templates_project_id
    ON templates (project_id);
CREATE INDEX idx_templates_project_channel
    ON templates (project_id, channel);

-- recipients
CREATE INDEX idx_recipients_project_id
    ON recipients (project_id);
CREATE INDEX idx_recipients_active
    ON recipients (project_id)
    WHERE archived_at IS NULL;

-- notifications
CREATE INDEX idx_notifications_project_id
    ON notifications (project_id);
CREATE INDEX idx_notifications_recipient_id
    ON notifications (recipient_id);
CREATE INDEX idx_notifications_project_status
    ON notifications (project_id, status);
CREATE INDEX idx_notifications_project_channel
    ON notifications (project_id, channel);
CREATE INDEX idx_notifications_scheduled_at
    ON notifications (scheduled_at)
    WHERE scheduled_at IS NOT NULL;
CREATE INDEX idx_notifications_correlation_id
    ON notifications (correlation_id);
CREATE INDEX idx_notifications_project_created
    ON notifications (project_id, created_at DESC);

-- delivery_attempts
CREATE INDEX idx_delivery_attempts_notification_id
    ON delivery_attempts (notification_id);
CREATE INDEX idx_delivery_attempts_provider_message_id
    ON delivery_attempts (provider_message_id)
    WHERE provider_message_id IS NOT NULL;
CREATE INDEX idx_delivery_attempts_status
    ON delivery_attempts (status);

-- providers
CREATE INDEX idx_providers_channel_health
    ON providers (channel, is_active, is_healthy);

-- webhook_endpoints
CREATE INDEX idx_webhook_endpoints_project_id
    ON webhook_endpoints (project_id);

-- webhook_events
CREATE INDEX idx_webhook_events_endpoint_id
    ON webhook_events (endpoint_id);
CREATE INDEX idx_webhook_events_notification_id
    ON webhook_events (notification_id);
CREATE INDEX idx_webhook_events_status
    ON webhook_events (endpoint_id, status);

-- blackout_periods
CREATE INDEX idx_blackout_periods_policy_id
    ON blackout_periods (delivery_policy_id);
CREATE INDEX idx_blackout_periods_dates
    ON blackout_periods (start_date, end_date);

-- compliance_rules
CREATE INDEX idx_compliance_rules_policy_id
    ON compliance_rules (delivery_policy_id);

-- engagement_events
CREATE INDEX idx_engagement_events_notification_id
    ON engagement_events (notification_id);
CREATE INDEX idx_engagement_events_recipient_id
    ON engagement_events (recipient_id);
CREATE INDEX idx_engagement_events_project_id
    ON engagement_events (project_id);
CREATE INDEX idx_engagement_events_project_type
    ON engagement_events (project_id, event_type);
CREATE INDEX idx_engagement_events_occurred_at
    ON engagement_events (occurred_at DESC);
CREATE INDEX idx_engagement_events_real_occurred
    ON engagement_events (project_id, occurred_at DESC)
    WHERE is_synthetic = FALSE;

-- model_versions
CREATE INDEX idx_model_versions_type_status
    ON model_versions (model_type, status);
CREATE INDEX idx_model_versions_training_run_id
    ON model_versions (training_run_id);
CREATE UNIQUE INDEX uq_active_model_per_type
    ON model_versions (model_type)
    WHERE status = 'active';

-- training_runs
CREATE INDEX idx_training_runs_type_status
    ON training_runs (model_type, status);
CREATE INDEX idx_training_runs_started_at
    ON training_runs (started_at DESC);