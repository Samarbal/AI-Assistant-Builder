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


def test_knowledge_migration_is_additive_and_secured_before_commit(monkeypatch):
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql+psycopg://offline:placeholder@localhost/offline")
    root = Path(__file__).resolve().parents[1]
    output = StringIO()
    config = Config(str(root / 'alembic.ini'), output_buffer=output)
    config.set_main_option('script_location', str(root / 'alembic'))
    command.upgrade(config, '0002_assistant_owner_rls:0003_knowledge_files', sql=True)
    sql = output.getvalue()
    for table in ('knowledge_files', 'knowledge_file_text'):
        assert f'CREATE TABLE public.{table}' in sql
        assert f'ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY' in sql
        assert f'REVOKE ALL PRIVILEGES ON TABLE public.{table}' in sql
        assert f'REVOKE ALL PRIVILEGES (%I) ON TABLE public.{table}' in sql
        assert f'GRANT SELECT, INSERT ON public.{table} TO assistant_runtime' in sql
    assert 'UNIQUE (assistant_id, slot_number)' in sql
    assert 'REFERENCES public.assistants (id, owner_id)' in sql
    assert 'REFERENCES public.knowledge_files (id, assistant_id, owner_id)' in sql
    assert 'WITH CHECK' in sql
    assert 'GRANT DELETE' not in sql
    assert 'DISABLE ROW LEVEL SECURITY' not in sql
    assert 'DROP TABLE' not in sql
    assert 'storage.objects' not in sql
    assert sql.count('COMMIT;') == 1
