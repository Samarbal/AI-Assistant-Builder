import pytest
from pydantic import ValidationError
from assistant_builder.config import Settings, MigrationSettings


def test_runtime_never_falls_back_to_migration_or_components():
    config = Settings(_env_file=None, MIGRATION_DATABASE_URL="migration", host="host", user="postgres")
    assert config.database_url is None


def test_alembic_requires_explicit_migration_connection():
    with pytest.raises(ValidationError):
        MigrationSettings(_env_file=None, DATABASE_URL="runtime")


def test_urls_are_not_in_settings_repr():
    assert "private-secret" not in repr(Settings(_env_file=None, database_url="private-secret"))
    assert "private-secret" not in repr(MigrationSettings(_env_file=None, migration_database_url="private-secret"))
