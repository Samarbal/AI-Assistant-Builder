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


def test_versioned_index_migration_is_reviewable_and_fail_closed(monkeypatch):
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql+psycopg://offline:placeholder@localhost/offline")
    root = Path(__file__).resolve().parents[1]
    output = StringIO()
    config = Config(str(root / 'alembic.ini'), output_buffer=output)
    config.set_main_option('script_location', str(root / 'alembic'))
    command.upgrade(config, '0003_knowledge_files:0004_versioned_knowledge_indexes', sql=True)
    sql = output.getvalue()
    assert "e.extname='vector'" in sql and "n.nspname='public'" in sql
    assert "t.typname='vector'" in sql
    assert "has_schema_privilege('assistant_runtime','public','USAGE')" in sql
    assert "NOT rolsuper AND NOT rolbypassrls" in sql
    assert "Unexpected indexing schema objects already exist" in sql
    assert "CREATE EXTENSION" not in sql
    for table in ('knowledge_indexes', 'knowledge_index_sources',
                  'knowledge_index_batches', 'knowledge_chunks'):
        assert f'CREATE TABLE public.{table}' in sql
        assert f'ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY' in sql
        assert f'GRANT SELECT, INSERT ON public.{table} TO assistant_runtime' in sql
        assert f'FOR UPDATE TO assistant_runtime' in sql
    creation_positions = [sql.index(f'CREATE TABLE public.{table}') for table in (
        'knowledge_indexes', 'knowledge_index_sources',
        'knowledge_index_batches', 'knowledge_chunks')]
    assert creation_positions == sorted(creation_positions)
    assert sql.index('ALTER TABLE public.assistants ADD CONSTRAINT fk_assistant_active_index') > creation_positions[-1]
    assert 'REFERENCES public.knowledge_indexes(id,assistant_id,owner_id)' in sql
    assert 'REFERENCES public.knowledge_index_sources(index_id,file_id,assistant_id,owner_id)' in sql
    assert 'embedding public.vector(768)' in sql
    assert 'GRANT USAGE ON SCHEMA extensions TO assistant_runtime' not in sql
    from assistant_builder.models import Vector768
    assert Vector768().get_col_spec() == 'public.vector(768)'
    assert 'REFERENCES public.assistants(id, owner_id)' in sql
    assert 'REFERENCES public.knowledge_files(' in sql
    assert 'active_knowledge_index_id' in sql
    assert 'CREATE UNIQUE INDEX uq_index_one_building' in sql
    assert "state='building' AND completed_chunks=0 AND ready_at IS NULL" in sql
    assert 'ck_index_ready_complete' in sql
    assert 'GRANT DELETE' not in sql
    assert 'DISABLE ROW LEVEL SECURITY' not in sql
    assert 'DROP TABLE' not in sql
    assert sql.count('COMMIT;') == 1


def test_vector_model_uses_public_schema_for_postgres_and_sqlite_test_type():
    from sqlalchemy.dialects import postgresql, sqlite
    from sqlalchemy.schema import CreateTable
    from assistant_builder.models import KnowledgeChunk
    postgres_sql = str(CreateTable(KnowledgeChunk.__table__).compile(dialect=postgresql.dialect()))
    sqlite_sql = str(CreateTable(KnowledgeChunk.__table__).compile(dialect=sqlite.dialect()))
    assert 'embedding public.vector(768)' in postgres_sql
    assert 'embedding vector(768)' in sqlite_sql


def test_index_batch_idempotency_grant_is_narrow_and_requires_forced_rls(monkeypatch):
    # Offline SQL only: verify the additive correction without touching a database.
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql+psycopg://offline:placeholder@localhost/offline")
    root = Path(__file__).resolve().parents[1]
    output = StringIO()
    config = Config(str(root / 'alembic.ini'), output_buffer=output)
    config.set_main_option('script_location', str(root / 'alembic'))
    command.upgrade(config, '0004_versioned_knowledge_indexes:head', sql=True)
    sql = output.getvalue()
    assert "knowledge_index_batches must retain forced RLS" in sql
    assert "owner-scoped batch UPDATE policy" in sql
    assert "assistant_runtime'::name = ANY(roles)" in sql
    assert "qual LIKE '%app.owner_id%'" in sql
    assert "with_check LIKE '%app.owner_id%'" in sql
    assert "GRANT UPDATE (idempotency_key) ON public.knowledge_index_batches TO assistant_runtime" in sql
    assert "GRANT UPDATE ON public.knowledge_index_batches" not in sql
    assert "GRANT DELETE" not in sql
    assert "DISABLE ROW LEVEL SECURITY" not in sql
    assert "DROP TABLE" not in sql
