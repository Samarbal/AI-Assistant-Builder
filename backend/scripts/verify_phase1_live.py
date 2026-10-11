"""Authorized live verification. No migrations, truncate, or RLS changes.

Database fixtures are rolled back. Optional real-auth API fixtures are committed
and retained unless explicitly requesting exact current-run fixture cleanup.
"""
import json
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from assistant_builder.auth import SupabaseAuthVerifier
from assistant_builder.config import Settings, MigrationSettings
from assistant_builder.db import set_owner_identity, validate_runtime_role
from assistant_builder.main import create_app
from assistant_builder.repositories import AssistantRepository
from assistant_builder.schemas import AssistantCreate
from phase1_baseline import verify_baseline

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT.parent / 'docs/ai-sdlc/contracts/PHASE-1-LIVE-RESULTS.json'


def payload(label):
    return dict(name=label, role='Phase 1 verification fixture', colors={'primary':'#123456'},
                response_style='concise', tone='friendly', fallback_message='No information available.')


def cleanup_fixtures(admin, fixtures):
    """Delete only successful current-run fixtures after validating every identity.

    Never used on verification failure; no historical manifest or broad filter.
    Refuse triggers, referencing FKs and rules that could affect other records.
    """
    if not fixtures:
        return
    with admin.begin() as connection:
        connection.execute(text('SET LOCAL lock_timeout = \'5s\''))
        connection.execute(text('LOCK TABLE public.assistants IN ROW EXCLUSIVE MODE'))
        hazards = connection.scalar(text("""
            SELECT EXISTS (SELECT 1 FROM pg_trigger
                WHERE tgrelid='public.assistants'::regclass AND NOT tgisinternal)
              OR EXISTS (SELECT 1 FROM pg_constraint
                WHERE confrelid='public.assistants'::regclass AND contype='f')
              OR EXISTS (SELECT 1 FROM pg_rewrite
                WHERE ev_class='public.assistants'::regclass)
        """))
        if hazards:
            raise RuntimeError('Unexpected cleanup dependency; retain fixtures for review')
        for fixture in fixtures:
            row = connection.execute(text('SELECT owner_id, role, state FROM public.assistants WHERE id=:id FOR UPDATE'), fixture).one()
            if str(row.owner_id) != fixture['owner'] or row.role != fixture['role'] or row.state != 'draft':
                raise RuntimeError('Fixture changed; cleanup stopped')
        for fixture in fixtures:
            result = connection.execute(text("DELETE FROM public.assistants WHERE id=:id AND owner_id=:owner AND role=:role AND state='draft'"), fixture)
            if result.rowcount != 1:
                raise RuntimeError('Unexpected cleanup count; transaction rolled back')


def main(tokens=None, cleanup=False):
    report = {'date':'2026-10-11', 'passed':[], 'skipped':[], 'retained_assistant_ids':[]}
    settings = Settings()
    admin = create_engine(MigrationSettings().migration_database_url, hide_parameters=True, connect_args={'connect_timeout':8})
    runtime = create_engine(settings.database_url, hide_parameters=True, pool_size=1, max_overflow=0, connect_args={'connect_timeout':8})
    factory = sessionmaker(runtime, expire_on_commit=False)
    stage = 'read-only deployment verification'
    def passed(name):
        report['passed'].append(name)
        print('PASS:', name, flush=True)
    def denied(session, statement, params=None, state='42501'):
        try:
            with session.begin_nested():
                session.execute(text(statement), params or {})
        except DBAPIError as exc:
            assert getattr(exc.orig, 'sqlstate', None) == state, 'Unexpected SQLSTATE'
        else:
            raise AssertionError('Expected database denial was not enforced')
    try:
        with admin.connect() as connection:
            connection.execute(text('SET TRANSACTION READ ONLY'))
            verify_baseline(connection)
            revision = connection.scalar(text('SELECT version_num FROM public.alembic_version'))
            assert revision == '0002_assistant_owner_rls'
            report['revision'] = revision
            passed('migration head and unchanged approved trigger')
            assert connection.execute(text("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.assistants'::regclass")).one() == (True,True)
            for table in ('assistants','alembic_version'):
                for role in ('anon','authenticated','service_role'):
                    for priv in ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER'):
                        assert not connection.scalar(text('SELECT has_table_privilege(:role,:table,:priv)'),dict(role=role,table='public.'+table,priv=priv))
                    for priv in ('SELECT','INSERT','UPDATE','REFERENCES'):
                        assert not connection.scalar(text('SELECT has_any_column_privilege(:role,:table,:priv)'),dict(role=role,table='public.'+table,priv=priv))
            passed('RLS enabled/forced; no Data API table or column grants')
        stage = 'restricted runtime login'
        validate_runtime_role(runtime)
        with runtime.connect() as connection:
            assert connection.scalar(text('SELECT current_user')) == 'assistant_runtime'
            assert not connection.scalar(text("SELECT has_table_privilege(current_user,'public.alembic_version','SELECT')"))
            editable = {'name','role','colors','response_style','tone','fallback_message','updated_at'}
            columns = connection.execute(text("SELECT attname,has_column_privilege(current_user,'public.assistants',attname,'UPDATE') FROM pg_attribute WHERE attrelid='public.assistants'::regclass AND attnum>0 AND NOT attisdropped")).all()
            assert {name for name, allowed in columns if allowed} == editable
            for priv in ('DELETE','TRUNCATE','REFERENCES','TRIGGER'):
                assert not connection.scalar(text("SELECT has_table_privilege(current_user,'public.assistants',:priv)"), {'priv':priv})
        passed('actual runtime login and exact least-privilege UPDATE grants')
        stage = 'rollback-only owner isolation fixtures'
        owner_a, owner_b = uuid4(), uuid4()
        ids = []
        with factory() as session:
            transaction = session.begin()
            try:
                repo = AssistantRepository(session)
                for owner in (owner_a, owner_a, owner_b):
                    set_owner_identity(session, owner)
                    ids.append(repo.create(owner, AssistantCreate(**payload('Rollback-only fixture'))).id)
                set_owner_identity(session, owner_a)
                assert set(session.scalars(text('SELECT id FROM public.assistants'))) == set(ids[:2])
                assert session.execute(text("UPDATE public.assistants SET tone='wrong' WHERE id=:id"), {'id':ids[2]}).rowcount == 0
                set_owner_identity(session, owner_b)
                assert session.scalars(text('SELECT id FROM public.assistants')).all() == [ids[2]]
                passed('two owner UUIDs isolated in raw SQL; cross-owner UPDATE hidden')
                denied(session, 'UPDATE public.assistants SET owner_id=:owner WHERE id=:id', {'owner':owner_a,'id':ids[2]})
                denied(session, 'DELETE FROM public.assistants WHERE id=:id', {'id':ids[2]})
                # Reuse a complete existing row to test WITH CHECK without unrelated NOT NULL errors.
                denied(session, 'INSERT INTO public.assistants SELECT :new_id,:owner,name,role,colors,response_style,tone,fallback_message,state,created_at,updated_at FROM public.assistants WHERE id=:id', {'new_id':uuid4(),'owner':owner_a,'id':ids[2]})
                passed('owner_id UPDATE, DELETE, and forged owner INSERT denied')
                session.execute(text("SELECT set_config('app.owner_id','',true)"))
                assert session.scalars(text('SELECT id FROM public.assistants')).all() == []
                denied(session, "INSERT INTO public.assistants(id,owner_id,name,role,colors,response_style,tone,fallback_message,state) VALUES (:id,:owner,'test','test','{}','test','test','test','draft')", {'id':uuid4(),'owner':owner_a})
                session.execute(text("SELECT set_config('app.owner_id','invalid',true)"))
                denied(session, 'SELECT id FROM public.assistants', state='22P02')
                passed('empty and invalid identity fail closed')
            finally:
                transaction.rollback()
        with factory.begin() as session:
            assert session.scalars(text('SELECT id FROM public.assistants')).all() == []
            set_owner_identity(session, owner_a)
            assert session.scalars(text('SELECT id FROM public.assistants')).all() == []
        with factory.begin() as session:
            assert session.scalars(text('SELECT id FROM public.assistants')).all() == []
            set_owner_identity(session, owner_b)
            assert session.scalars(text('SELECT id FROM public.assistants')).all() == []
        passed('rollback removed all transient fixtures; connection reuse after rollback/commit fails closed')
        stage = 'authenticated owners API verification'
        env = dotenv_values(ROOT / '.env')
        tokens = tokens or [env.get('PHASE1_OWNER_A_TOKEN'), env.get('PHASE1_OWNER_B_TOKEN')]
        if not all(tokens):
            report['skipped'].append('Two authenticated Supabase owners: PHASE1_OWNER_A_TOKEN / PHASE1_OWNER_B_TOKEN unavailable; no auth bypass used')
        else:
            verifier = SupabaseAuthVerifier(settings.supabase_url, settings.supabase_anon_key)
            try:
                owners = [verifier.verify('Bearer '+token).owner_id for token in tokens]
            finally:
                verifier.client.close()
            assert owners[0] != owners[1], 'Two distinct authenticated accounts required'
            fixtures = []
            marker = 'Phase 1 verification fixture ' + str(uuid4())
            with TestClient(create_app()) as client:
                headers = [{'Authorization':'Bearer '+token} for token in tokens]
                for index in (0,0,1):
                    data = payload('Phase 1 verified fixture '+str(uuid4())[:8])
                    data['role'] = marker
                    response = client.post('/assistants', json=data, headers=headers[index])
                    assert response.status_code == 201
                    item = response.json()
                    assert item['owner_id'] == str(owners[index]) and item['state'] == 'draft'
                    report['retained_assistant_ids'].append(item['id'])
                    fixtures.append({'id':item['id'], 'owner':str(owners[index]), 'role':marker})
                a1,a2,b1 = report['retained_assistant_ids']
                values = payload('Phase 1 configuration verified')
                values['role'] = marker
                values['tone'] = 'formal'
                assert client.patch('/assistants/'+a1,json=values,headers=headers[0]).status_code == 200
                saved = client.get('/assistants/'+a1,headers=headers[0]).json()
                assert all(saved[key] == value for key,value in values.items())
                assert client.get('/assistants/'+a2,headers=headers[0]).json()['tone'] == 'friendly'
                for own,other,h in (({a1,a2},b1,headers[0]),({b1},a1,headers[1])):
                    listed = client.get('/assistants',headers=h)
                    assert listed.status_code == 200
                    assert all(x['owner_id'] == str(owners[headers.index(h)]) for x in listed.json())
                    assert own <= {x['id'] for x in listed.json()}
                    assert other not in {x['id'] for x in listed.json()}
                    assert client.get('/assistants/'+other,headers=h).status_code == 404
                    assert client.patch('/assistants/'+other,json={'tone':'wrong'},headers=h).status_code == 404
                assert client.get('/assistants').status_code == 401
                assert client.patch('/assistants/'+a1,json={'owner_id':str(owners[1])},headers=headers[0]).status_code == 422
            passed('real Supabase Auth owners: API commit, all configuration fields, independent assistants, isolation and input rejection')
            if cleanup:
                stage = 'exact current-run fixture cleanup'
                cleanup_fixtures(admin, fixtures)
                report['cleaned_fixture_count'] = len(fixtures)
                report['retained_assistant_ids'] = []
                passed('exact current-run fixtures cleaned; runtime DELETE remains forbidden')
        report['status'] = 'verified' if not report['skipped'] else 'database verified; authenticated-owner acceptance pending'
    except Exception as exc:
        report['status'] = 'STOP: unexpected verification failure'
        report['failed_stage'] = stage
        report['error_type'] = type(exc).__name__
        # Deliberately omit exception SQL/response content and credentials.
        raise SystemExit(1) from None
    finally:
        runtime.dispose()
        admin.dispose()
        REPORT.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
