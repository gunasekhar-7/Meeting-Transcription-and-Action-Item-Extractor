"""Typed application settings with fail-fast production validation."""

from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET = "dev-only-insecure-secret-change-me-32-bytes"


class Settings(BaseSettings):
    """Environment-driven configuration.

    Every field maps to an environment variable of the same name (case-insensitive).
    Nothing security-sensitive has a usable production default.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "local"
    app_name: str = "Meeting Intelligence"
    api_prefix: str = "/api/v1"

    database_url: str = "sqlite:///./data/app.db"

    jwt_secret: str = INSECURE_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7

    storage_backend: str = "local"
    local_storage_path: str = "./data/audio"
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = None

    max_upload_mb: int = 200
    max_audio_minutes: int = 180

    asr_provider: str = "fake"
    asr_model: str = "small"
    asr_compute_type: str = "int8"
    asr_beam_size: int = 5

    diarization_provider: str = "none"
    diarization_model: str = "pyannote/speaker-diarization-3.1"
    hf_token: str | None = None

    llm_provider: str = "rule_based"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str = "gpt-6-luna"
    llm_timeout_seconds: int = 60
    llm_input_price_per_million: float = 0.10
    llm_output_price_per_million: float = 0.50
    prompt_version: str = "2026-11-02.1"
    schema_version: str = "1.0.0"

    jobs_mode: str = "inline"
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False

    cors_origins: str = "http://localhost:8501"
    api_docs_enabled: bool = True
    log_level: str = "INFO"
    rate_limit_enabled: bool = True
    rate_limit_backend: str = "memory"
    audio_retention_days: int = 30

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.env == "production":
            if self.jwt_secret == INSECURE_SECRET or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be set to a unique value of at least 32 characters")
            if self.api_docs_enabled:
                raise ValueError("API_DOCS_ENABLED must be false in production")
            if "*" in self.cors_origin_list:
                raise ValueError("CORS_ORIGINS must not contain a wildcard in production")
        if self.storage_backend not in {"local", "s3"}:
            raise ValueError("STORAGE_BACKEND must be 'local' or 's3'")
        if self.asr_provider not in {"fake", "faster_whisper"}:
            raise ValueError("ASR_PROVIDER must be 'fake' or 'faster_whisper'")
        if self.diarization_provider not in {"none", "fake", "pyannote"}:
            raise ValueError("DIARIZATION_PROVIDER must be 'none', 'fake', or 'pyannote'")
        if self.rate_limit_backend not in {"memory", "redis", "auto"}:
            raise ValueError("RATE_LIMIT_BACKEND must be 'memory', 'redis', or 'auto'")
        if self.llm_provider not in {"rule_based", "openai_compatible"}:
            raise ValueError("LLM_PROVIDER must be 'rule_based' or 'openai_compatible'")
        if self.jobs_mode not in {"inline", "celery"}:
            raise ValueError("JOBS_MODE must be 'inline' or 'celery'")
        if self.llm_provider == "openai_compatible" and not self.llm_api_key:
            raise ValueError("LLM_API_KEY is required when LLM_PROVIDER=openai_compatible")
        if self.llm_model in {"gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"}:
            raise ValueError(
                "This model is retired by OpenAI on 2027-01-14. Set LLM_MODEL to a current model."
            )
        if self.asr_provider == "faster_whisper" and self.asr_model.startswith("large"):
            import os

            if os.getenv("ALLOW_SLOW_CPU_MODELS", "").lower() not in {"1", "true"}:
                raise ValueError(
                    "large-* Whisper models are not real-time on CPU. "
                    "Set ALLOW_SLOW_CPU_MODELS=1 to override."
                )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

