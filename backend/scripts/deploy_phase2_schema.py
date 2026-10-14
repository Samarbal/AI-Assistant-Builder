"""Apply only the approved additive 0003 migration, with fail-closed preflight."""
import logging
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from assistant_builder.config import MigrationSettings, Settings
from assistant_builder.db import validate_runtime_role
from phase1_baseline import verify_baseline


def main():
    settings = Settings()
    admin_url = MigrationSettings().migration_database_url
    runtime_url = settings.database_url
    project = urlparse(settings.supabase_url or '').hostname
    assert project and project.endswith('.supabase.co'), 'Supabase project required'
    ref = project.split('.')[0]
    for value in (admin_url, runtime_url):
        url = make_url(value)
        assert ref in (url.host or '') or (url.username or '').endswith('.' + ref), 'Target differs'
        assert url.database == 'postgres', 'Unexpected database'
    runtime = create_engine(runtime_url, hide_parameters=True)
    admin = create_engine(admin_url, hide_parameters=True)
    try:
        validate_runtime_role(runtime)
        with admin.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            connection.execute(text("SET LOCAL statement_timeout = '60s'"))
            connection.execute(text('SELECT pg_advisory_xact_lock(732031)'))
            verify_baseline(connection)
            assert connection.scalar(text('SELECT current_user')) == 'postgres'
            assert connection.scalars(text('SELECT version_num FROM public.alembic_version')).all() == ['0002_assistant_owner_rls']
            tables = set(connection.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")))
            assert tables == {'assistants', 'alembic_version'}, 'Unexpected tables; stop for review'
            assert connection.scalar(text('SELECT count(*) FROM public.assistants')) == 0, 'Application data found; review before deployment'
            for name in ('knowledge_files', 'knowledge_file_text'):
                assert connection.scalar(text('SELECT to_regclass(:name)'), {'name': 'public.' + name}) is None
            policies = connection.scalar(text("SELECT count(*) FROM pg_policies WHERE schemaname='storage' AND tablename='objects'"))
            print('PASS: target, runtime role, baseline and migration preflight; Storage policies:', policies)
            cfg = Config('alembic.ini')
            cfg.attributes['connection'] = connection
            command.upgrade(cfg, '0003_knowledge_files')
            assert connection.scalar(text('SELECT version_num FROM public.alembic_version')) == '0003_knowledge_files'
            for table in ('knowledge_files', 'knowledge_file_text'):
                assert connection.scalar(text("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:t)"), {'t': 'public.' + table})
                for role in ('anon', 'authenticated', 'service_role', 'assistant_runtime'):
                    for privilege in ('DELETE', 'TRUNCATE') if role == 'assistant_runtime' else ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
                        assert not connection.scalar(text('SELECT has_table_privilege(:r,:t,:p)'), {'r':role,'t':'public.'+table,'p':privilege})
            verify_baseline(connection)
        print('PASS: committed 0003_knowledge_files; forced RLS and restricted grants verified')
    finally:
        runtime.dispose()
        admin.dispose()


if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    try:
        main()
    except Exception as exc:
        print('STOP: deployment failed; no further changes attempted. Error type:', type(exc).__name__)
        raise SystemExit(1) from None
