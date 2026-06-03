"""
Application configuration loaded from environment variables.

All configuration goes through this module. Never read os.environ directly
from anywhere else in the app.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---------------------------------------------------------------------
    # General
    # ---------------------------------------------------------------------
    ENV: Literal["development", "staging", "production"] = "development"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    SECRET_KEY: str = Field(..., min_length=32)
    TIMEZONE: str = "UTC"

    # ---------------------------------------------------------------------
    # API
    # ---------------------------------------------------------------------
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    BACKEND_CORS_ORIGINS: list[str] = Field(default_factory=list)
    API_V1_PREFIX: str = "/api/v1"

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # ---------------------------------------------------------------------
    # Database
    # ---------------------------------------------------------------------
    DATABASE_URL: str
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False

    # ---------------------------------------------------------------------
    # Redis & Celery
    # ---------------------------------------------------------------------
    REDIS_URL: RedisDsn
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # ---------------------------------------------------------------------
    # S3 / object storage
    # ---------------------------------------------------------------------
    S3_ENDPOINT: str | None = None
    S3_BUCKET: str
    S3_REGION: str = "us-east-1"
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_USE_SSL: bool = False

    # ---------------------------------------------------------------------
    # LLM
    # ---------------------------------------------------------------------
    LLM_PROVIDER: Literal["anthropic", "openai", "local"] = "anthropic"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL_DEFAULT: str = "claude-sonnet-4-5"
    ANTHROPIC_MODEL_REASONING: str = "claude-opus-4-7"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL_DEFAULT: str = "gpt-4o"

    EMBEDDING_PROVIDER: Literal["openai", "voyage", "local"] = "openai"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536

    # ---------------------------------------------------------------------
    # OCR
    # ---------------------------------------------------------------------
    OCR_PROVIDER: Literal["azure", "aws", "google", "local"] = "azure"
    AZURE_DI_ENDPOINT: str = ""
    AZURE_DI_KEY: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"

    # ---------------------------------------------------------------------
    # Auth
    # ---------------------------------------------------------------------
    APP_BASE_URL: str = "http://localhost:8000"
    AUTH_PROVIDER: Literal["local", "clerk", "auth0"] = "local"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    CLERK_SECRET_KEY: str = ""
    CLERK_PUBLISHABLE_KEY: str = ""
    AUTH0_DOMAIN: str = ""
    AUTH0_CLIENT_ID: str = ""
    AUTH0_CLIENT_SECRET: str = ""

    # ---------------------------------------------------------------------
    # Email
    # ---------------------------------------------------------------------
    EMAIL_PROVIDER: Literal["smtp", "sendgrid", "postmark", "ses"] = "smtp"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "no-reply@example.com"

    # ---------------------------------------------------------------------
    # FX
    # ---------------------------------------------------------------------
    FX_PROVIDER: Literal["ecb", "openexchangerates", "manual"] = "ecb"
    OPENEXCHANGERATES_APP_ID: str = ""

    # ---------------------------------------------------------------------
    # Observability
    # ---------------------------------------------------------------------
    SENTRY_DSN: str = ""
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    PROMETHEUS_ENABLED: bool = True

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
