from functools import lru_cache
from pydantic import Field

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Deployment configuration; secrets are supplied by the environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Assistant Builder API"
    database_url: str | None = Field(default=None, repr=False)
    environment: str = "development"
    supabase_url: str | None = None
    supabase_anon_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()


class MigrationSettings(BaseSettings):
    """Read only by Alembic; never a runtime fallback."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    migration_database_url: str = Field(min_length=1, repr=False)
