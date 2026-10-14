"""Real PostgreSQL tests. Reuse guarded loopback-only Phase 1 provisioning.

Never reads .env; never redirects tests to Supabase. Admin is test setup/cleanup only.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from assistant_builder.db import set_owner_identity
from assistant_builder.models import Assistant
from assistant_builder.knowledge_repository import KnowledgeRepository, KnowledgeLimitReached
from .test_postgresql_phase1 import postgres  # guarded, opt-in fixture
from .test_phase1_contracts import payload
from .test_knowledge_repository import reserve


@pytest.fixture
def corpus(postgres):
    admin, runtime = postgres
    # Two simultaneous connections are essential to exercise actual contention.
    engine = create_engine(runtime.url, hide_parameters=True, pool_size=2, max_overflow=0)
    factory = sessionmaker(engine, expire_on_commit=False)
    owners, ids = [uuid4(), uuid4()], []
    try:
        for owner in owners:
            with factory.begin() as session:
                set_owner_identity(session, owner)
                item = Assistant(owner_id=owner, **payload())
                session.add(item)
                session.flush()
                ids.append(item.id)
        yield factory, owners, ids
    finally:
        # This fixture runs only in the dedicated local DB; exact generated owners.
        with admin.begin() as connection:
            for owner in owners:
                for table in ('knowledge_file_text', 'knowledge_files', 'assistants'):
                    connection.execute(text(f'DELETE FROM public.{table} WHERE owner_id=:owner'), {'owner': owner})
        engine.dispose()


def test_raw_owner_isolation_text_and_missing_identity(corpus):
    factory, owners, assistants = corpus
    for owner, assistant in zip(owners, assistants):
        with factory.begin() as session:
            set_owner_identity(session, owner)
            repo = KnowledgeRepository(session)
            item = reserve(repo, owner, assistant)
            repo.start_processing(owner, assistant, item.id, item.operation_id)
            repo.complete_extraction(owner, assistant, item.id, item.operation_id,
                extracted_text='private', extraction_version='v1')
    for owner in owners:
        with factory.begin() as session:
            set_owner_identity(session, owner)
            for table in ('knowledge_files', 'knowledge_file_text'):
                assert session.scalars(text(f'SELECT owner_id FROM {table}')).all() == [owner]
    with factory.begin() as session:
        for table in ('knowledge_files', 'knowledge_file_text'):
            assert session.execute(text(f'SELECT * FROM {table}')).all() == []


def test_concurrent_last_slot(corpus):
    factory, owners, assistants = corpus
    with factory.begin() as session:
        set_owner_identity(session, owners[0])
        for _ in range(4):
            reserve(KnowledgeRepository(session), owners[0], assistants[0])
    barrier = Barrier(2)
    def upload():
        barrier.wait(timeout=10)
        try:
            with factory.begin() as session:
                set_owner_identity(session, owners[0])
                session.execute(text("SET LOCAL lock_timeout='5s'"))
                reserve(KnowledgeRepository(session), owners[0], assistants[0])
            return 'reserved'
        except KnowledgeLimitReached:
            return 'full'
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(upload), pool.submit(upload)]
        assert sorted(f.result(timeout=15) for f in futures) == ['full', 'reserved']
    with factory.begin() as session:
        set_owner_identity(session, owners[0])
        assert session.scalar(text('SELECT count(*) FROM knowledge_files')) == 5


@pytest.mark.parametrize('column', ['owner_id', 'assistant_id', 'object_key', 'id'])
def test_identity_columns_cannot_be_updated(corpus, column):
    factory, owners, assistants = corpus
    with pytest.raises(DBAPIError) as error, factory.begin() as session:
        set_owner_identity(session, owners[0])
        reserve(KnowledgeRepository(session), owners[0], assistants[0])
        session.execute(text(f'UPDATE knowledge_files SET {column}={column}'))
    assert error.value.orig.sqlstate == '42501'


@pytest.mark.parametrize('mutation,state', [
    ('slot_number=6', '23514'), ('size_bytes=10000001', '23514'),
    ("processing_state='ready'", '23514'), ('slot_number=NULL', '23514'),
    ("cleanup_state='unknown'", '23514'),
])
def test_database_constraints_without_repository(postgres, corpus, mutation, state):
    admin, _ = postgres
    factory, owners, assistants = corpus
    with factory.begin() as session:
        set_owner_identity(session, owners[0])
        item = reserve(KnowledgeRepository(session), owners[0], assistants[0])
    # Admin bypasses grants only to prove the constraints themselves hold.
    with pytest.raises(DBAPIError) as error, admin.begin() as conn:
        conn.execute(text(f'UPDATE knowledge_files SET {mutation} WHERE id=:id'), {'id': item.id})
    assert error.value.orig.sqlstate == state


def test_composite_fk_and_unique_slot(postgres, corpus):
    admin, _ = postgres
    factory, owners, assistants = corpus
    with factory.begin() as session:
        set_owner_identity(session, owners[0])
        first = reserve(KnowledgeRepository(session), owners[0], assistants[0])
        second = reserve(KnowledgeRepository(session), owners[0], assistants[0])
    for statement, args, state in [
        ('UPDATE knowledge_files SET assistant_id=:value WHERE id=:id', {'value': assistants[1], 'id': first.id}, '23503'),
        ('UPDATE knowledge_files SET slot_number=1 WHERE id=:id', {'id': second.id}, '23505'),
    ]:
        with pytest.raises(DBAPIError) as error, admin.begin() as conn:
            conn.execute(text(statement), args)
        assert error.value.orig.sqlstate == state


def test_forced_rls_and_grants(postgres):
    admin, runtime = postgres
    with runtime.connect() as conn:
        assert conn.scalar(text('SELECT current_user')) == 'assistant_runtime'
        for table in ('knowledge_files', 'knowledge_file_text'):
            assert conn.execute(text('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=CAST(:t AS regclass)'), {'t': table}).one() == (True, True)
            for privilege in ('DELETE', 'TRUNCATE', 'TRIGGER'):
                assert not conn.scalar(text('SELECT has_table_privilege(current_user,:t,:p)'), {'t':table,'p':privilege})
    with admin.connect() as conn:
        for role in ('anon', 'authenticated'):
            for table in ('knowledge_files', 'knowledge_file_text'):
                for privilege in ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES'):
                    assert not conn.scalar(text('SELECT has_any_column_privilege(:r,:t,:p)'), {'r':role,'t':table,'p':privilege})


def test_cross_owner_update_and_forged_text_insert(corpus):
    factory, owners, assistants = corpus
    with factory.begin() as session:
        set_owner_identity(session, owners[0])
        item = reserve(KnowledgeRepository(session), owners[0], assistants[0])
    with factory.begin() as session:
        set_owner_identity(session, owners[1])
        assert session.execute(text("UPDATE knowledge_files SET processing_state='failed' WHERE id=:id"), {'id':item.id}).rowcount == 0
    for identity, forged_owner, expected in ((None, owners[0], '42501'), (owners[1], owners[0], '42501'), (owners[1], owners[1], '23503')):
        with pytest.raises(DBAPIError) as error, factory.begin() as session:
            if identity:
                set_owner_identity(session, identity)
            session.execute(text("INSERT INTO knowledge_file_text(file_id,assistant_id,owner_id,extracted_text,extraction_version) VALUES (:id,:assistant,:owner,'text','v1')"),
                {'id':item.id,'assistant':assistants[0],'owner':forged_owner})
        assert error.value.orig.sqlstate == expected


def test_reservation_rollback_releases_slot(corpus):
    factory, owners, assistants = corpus
    with pytest.raises(RuntimeError), factory.begin() as session:
        set_owner_identity(session, owners[0])
        reserve(KnowledgeRepository(session), owners[0], assistants[0])
        raise RuntimeError('abort')
    with factory.begin() as session:
        assert session.execute(text('SELECT * FROM knowledge_files')).all() == []
        set_owner_identity(session, owners[0])
        item = reserve(KnowledgeRepository(session), owners[0], assistants[0])
        assert item.slot_number == 1
