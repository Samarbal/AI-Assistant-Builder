from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_upgrade_secures_version_table_before_single_commit(monkeypatch):
    # Offline SQL only: never use the developer's database or credentials.
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql+psycopg://offline:placeholder@localhost/offline")
    root = Path(__file__).resolve().parents[1]
    output = StringIO()
    config = Config(str(root / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert sql.count("BEGIN;") == 1
    assert sql.count("COMMIT;") == 1
    created = sql.index("CREATE TABLE public.alembic_version")
    secured = sql.index("REVOKE ALL PRIVILEGES ON TABLE public.alembic_version")
    assert created < secured < sql.index("COMMIT;")
    assert "REVOKE ALL PRIVILEGES (%I) ON TABLE public.alembic_version" in sql
    assert "ALTER TABLE public.alembic_version ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER DEFAULT PRIVILEGES" not in sql
