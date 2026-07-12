from functools import lru_cache
from typing import Literal

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

    # Database
    database_url: str = "postgresql+asyncpg://postgres:tiber@localhost:5432/tiber"
    database_sync_url: str = "postgresql+psycopg://postgres:tiber@localhost:5432/tiber"

    # RabbitMQ
    rabbitmq_url: str = "amqp://tiber:tiber@localhost:5672/"
    celery_result_backend: str = "redis://localhost:6379/3"

    # Redis (auth state, rate limiting, idempotency)
    redis_url: str = "redis://localhost:6379/2"

    # Auth
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10
    refresh_token_expire_days: int = 7

    # Rate limiting
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60

    # Idempotency
    idempotency_ttl_seconds: int = 86400

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
    email_provider: Literal["mock", "resend", "sendgrid"] = "mock"
    resend_api_key: str = ""
    sendgrid_api_key: str = ""

    push_provider: Literal["mock", "fcm"] = "mock"
    fcm_project_id: str = ""
    fcm_private_key: str = ""
    fcm_client_email: str = ""

    @property
    def celery_broker_url(self):
        """Both celery url and rabbitmq url are redis string."""
        return self.rabbitmq_url


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Use as a FastAPI dependency: Depends(get_settings)
    """
    return Settings()
