"""Default tests never load developer database credentials."""
import pytest
from assistant_builder.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    for key in ("DATABASE_URL", "MIGRATION_DATABASE_URL", "SUPABASE_URL", "SUPABASE_ANON_KEY"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr("assistant_builder.config.Settings", lambda: Settings(_env_file=None))
    yield
    get_settings.cache_clear()
