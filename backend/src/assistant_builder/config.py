from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Deployment configuration; secrets are supplied by the environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Assistant Builder API"
    database_url: str | None = None
    environment: str = "development"
    supabase_url: str | None = None
    supabase_anon_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
