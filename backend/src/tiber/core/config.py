from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Class to hold application settings, loaded from environment variables or a .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Tiber"
    app_version: str = "0.1.0"
    debug: bool = False
    cors_enabled: bool = True
    docs_enabled: bool = True
    redoc_enabled: bool = True
    openapi_enabled: bool = True
    cors_allow_origins: list[str] = ["http://localhost:3000"]
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]

    # Database
    database_url: str = "postgresql+asyncpg://postgres:tiber@localhost:5432/tiber"
    database_sync_url: str = "postgresql+psycopg://postgres:tiber@localhost:5432/tiber"

    # RabbitMQ
    rabbitmq_url: str = "amqp://tiber:tiber@localhost:5672/"

    # Redis (auth state, rate limiting, idempotency)
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    email_sender: str = ""
    dashboard_url: str = "http://localhost:3000"
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    github_oauth_redirect_uri: str = "http://localhost:8000/v1/auth/github/callback"

    # Rate limiting
    rate_limit_algorithm: Literal["sliding_window", "token_bucket", "gcra"] = (
        "sliding_window"
    )
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60
    rate_limit_auth_requests: int = 20
    rate_limit_dashboard_requests: int = 100
    rate_limit_api_requests: int = 100
    rate_limit_auth_window_seconds: int = 60
    rate_limit_dashboard_window_seconds: int = 60
    rate_limit_api_window_seconds: int = 60

    # Idempotency
    idempotency_ttl_seconds: int = 86400

    # Notification delivery retry (exponential backoff, bounded max attempts)
    notification_retry_max_attempts: int = 4
    notification_retry_base_delay_seconds: int = 30
    notification_retry_backoff_factor: int = 2
    notification_retry_max_delay_seconds: int = 3600
    notification_processing_lease_seconds: int = Field(default=300, ge=1)

    # Transactional outbox relay
    outbox_relay_interval_seconds: int = Field(default=1, ge=1)
    outbox_relay_batch_size: int = Field(default=100, ge=1)
    outbox_retry_max_attempts: int = Field(default=10, ge=1)
    outbox_retry_base_delay_seconds: int = Field(default=1, ge=1)
    outbox_retry_max_delay_seconds: int = Field(default=300, ge=1)

    # Object storage
    storage_endpoint: str = "localhost:9000"
    storage_access_key: str = "minioadmin"
    storage_secret_key: str = ""
    storage_bucket_models: str = "tiber-models"
    storage_bucket_datasets: str = "tiber-datasets"
    storage_secure: bool = False

    # Observability
    otlp_endpoint: str = ""

    # AI providers
    groq_api_key: str = ""
    gemini_api_key: str = ""

    # Notification providers
    email_provider: Literal["mock", "resend"] = "mock"
    resend_api_key: str = ""

    push_provider: Literal["mock", "fcm"] = "mock"
    fcm_project_id: str = ""

    sms_provider: Literal["mock", "twilio"] = "mock"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    @property
    def celery_broker_url(self):
        """Both celery url and rabbitmq url are redis string."""
        return self.rabbitmq_url

    @property
    def rabbitmq_user(self):
        """Extract rabbitmq user."""
        parsed = urlparse(self.rabbitmq_url)
        return parsed.username or ""

    @property
    def rabbitmq_password(self):
        """Extract rabbitmq password."""
        parsed = urlparse(self.rabbitmq_url)
        return parsed.password or ""


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Use as a FastAPI dependency: Depends(get_settings)
    """
    return Settings()
