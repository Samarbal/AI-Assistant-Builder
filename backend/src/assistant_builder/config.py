from functools import lru_cache
from pydantic import Field, SecretStr

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Deployment configuration; secrets are supplied by the environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Assistant Builder API"
    database_url: str | None = Field(default=None, repr=False)
    # Separate least-privilege public role; there is intentionally no owner-DB fallback.
    public_database_url: str | None = Field(default=None, repr=False)
    public_chat_enabled: bool = False
    # Comma-separated SHA-256 digests for at most two demo access tokens.
    public_demo_token_sha256: str | None = Field(default=None, repr=False)
    public_rate_limit_per_minute: int = Field(default=30, ge=1, le=30)
    public_max_concurrent: int = Field(default=2, ge=1, le=2)
    public_global_max_concurrent: int = Field(default=4, ge=1, le=4)
    public_rate_key_capacity: int = Field(default=4096, ge=32, le=4096)
    environment: str = "development"
    ai_base_url: str | None = Field(default=None, repr=False)
    ai_api_key: SecretStr | None = Field(default=None, repr=False)
    ai_model: str | None = None
    ai_timeout_seconds: float = Field(default=12, gt=0, le=12)
    embedding_base_url: str | None = Field(default=None, repr=False)
    embedding_api_key: SecretStr | None = Field(default=None, repr=False)
    embedding_model: str | None = None
    embedding_dimension: int = Field(default=768, ge=768, le=768)
    embedding_timeout_seconds: float = Field(default=12, gt=0, le=12)
    embedding_max_batch_size: int = Field(default=8, ge=1, le=8)
    embedding_max_input_tokens: int = Field(default=4800, ge=1, le=4800)
    # Calibrated offline/live-synthetic for the current embedding space; absent
    # means retrieval composition must fail closed instead of guessing a value.
    retrieval_min_similarity: float | None = Field(default=None, ge=0, le=1)
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_storage_key: str | None = Field(default=None, repr=False)
    supabase_storage_bucket: str = 'knowledge-files'
    storage_signed_url_seconds: int = Field(default=60, ge=1, le=300)
    widget_asset_origin: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()


class MigrationSettings(BaseSettings):
    """Read only by Alembic; never a runtime fallback."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    migration_database_url: str = Field(min_length=1, repr=False)
