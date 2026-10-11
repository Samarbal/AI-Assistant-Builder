"""Explicit opt-in, loopback-only PostgreSQL integration tests. Never use .env."""
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from assistant_builder.auth import OwnerContext, get_current_owner
from assistant_builder.db import set_owner_identity, validate_runtime_role
from assistant_builder.main import create_app
from assistant_builder.repositories import AssistantRepository
from assistant_builder.schemas import AssistantCreate
from .test_phase1_contracts import payload


@pytest.fixture(scope="module")
def postgres():
    if os.getenv("PHASE1_LOCAL_PG_TESTS") != "1":
        pytest.skip("Local PostgreSQL tests disabled; set PHASE1_LOCAL_PG_TESTS=1 and dedicated local URLs")
    admin_url = os.getenv("PHASE1_LOCAL_MIGRATION_URL")
    runtime_url = os.getenv("PHASE1_LOCAL_RUNTIME_URL")
    for url in (admin_url, runtime_url):
        if not url:
            pytest.fail("Both dedicated local PostgreSQL URLs are required", pytrace=False)
        parsed = make_url(url)
        if parsed.host not in ("localhost", "127.0.0.1", "::1") or parsed.database != "assistant_builder_phase1_test" or parsed.query:
            pytest.fail("Use loopback, database assistant_builder_phase1_test, and no URL query overrides", pytrace=False)
    admin = create_engine(admin_url, hide_parameters=True, connect_args={"connect_timeout": 5})
    runtime = create_engine(runtime_url, hide_parameters=True, pool_size=1, max_overflow=0, connect_args={"connect_timeout": 5})
    try:
        # Roles must be provisioned explicitly in this disposable local cluster.
        root = Path(__file__).resolve().parents[1]
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "alembic"))
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("MIGRATION_DATABASE_URL", admin_url)
            command.upgrade(config, "head")
        validate_runtime_role(runtime)
        yield admin, runtime
    finally:
        runtime.dispose()
        admin.dispose()


@pytest.fixture
def corpus(postgres):
    admin, runtime = postgres
    factory = sessionmaker(runtime, expire_on_commit=False)
    owners = [uuid4(), uuid4()]
    identifiers = []
    try:
        for owner in owners:
            with factory.begin() as session:
                set_owner_identity(session, owner)
                item = AssistantRepository(session).create(owner, AssistantCreate(**payload()))
                identifiers.append(item.id)
        yield factory, owners, identifiers
    finally:
        # Admin cleanup is restricted to test-generated owners, not runtime DELETE.
        with admin.begin() as conn:
            for owner in owners:
                conn.execute(text("DELETE FROM public.assistants WHERE owner_id=:owner"), {"owner": owner})


def test_raw_sql_owner_isolation_and_pooled_identity(corpus):
    factory, owners, ids = corpus
    for owner, identifier in zip(owners, ids):
        with factory.begin() as session:
            set_owner_identity(session, owner)
            assert session.scalars(text("SELECT id FROM public.assistants")).all() == [identifier]
            other = ids[1] if identifier == ids[0] else ids[0]
            assert session.execute(text("UPDATE public.assistants SET tone='wrong' WHERE id=:id"), {"id": other}).rowcount == 0
        with factory.begin() as session:
            assert session.scalars(text("SELECT id FROM public.assistants")).all() == []


@pytest.mark.parametrize("identity", [None, "", "not-a-uuid"])
def test_missing_or_invalid_identity_fails_closed(corpus, identity):
    factory, _, _ = corpus
    if identity == "not-a-uuid":
        with pytest.raises(DBAPIError), factory.begin() as session:
            session.execute(text("SELECT set_config('app.owner_id', :id, true)"), {"id": identity})
            session.execute(text("SELECT * FROM public.assistants"))
    else:
        with factory.begin() as session:
            if identity is not None:
                session.execute(text("SELECT set_config('app.owner_id', '', true)"))
            assert session.scalars(text("SELECT id FROM public.assistants")).all() == []
        with pytest.raises(DBAPIError), factory.begin() as session:
            AssistantRepository(session).create(uuid4(), AssistantCreate(**payload()))


def test_forged_insert_and_owner_update_rejected(corpus):
    factory, owners, ids = corpus
    with pytest.raises(DBAPIError), factory.begin() as session:
        set_owner_identity(session, owners[0])
        AssistantRepository(session).create(owners[1], AssistantCreate(**payload()))
    with pytest.raises(DBAPIError), factory.begin() as session:
        set_owner_identity(session, owners[0])
        session.execute(text("UPDATE public.assistants SET owner_id=:owner WHERE id=:id"), {"owner": owners[1], "id": ids[0]})


@pytest.mark.parametrize("sql", [
    "DELETE FROM public.assistants", "TRUNCATE public.assistants",
    "ALTER TABLE public.assistants DISABLE ROW LEVEL SECURITY", "SET ROLE postgres",
])
def test_runtime_forbidden_operations(corpus, sql):
    factory, owners, _ = corpus
    with pytest.raises(DBAPIError), factory.begin() as session:
        set_owner_identity(session, owners[0])
        session.execute(text(sql))


def test_rollback_clears_changes_and_identity(corpus):
    factory, owners, ids = corpus
    with pytest.raises(RuntimeError), factory.begin() as session:
        set_owner_identity(session, owners[0])
        session.execute(text("UPDATE public.assistants SET tone='rolled-back' WHERE id=:id"), {"id": ids[0]})
        AssistantRepository(session).create(owners[0], AssistantCreate(**payload()))
        raise RuntimeError("abort request")
    with factory.begin() as session:
        assert session.scalars(text("SELECT id FROM public.assistants")).all() == []
        set_owner_identity(session, owners[0])
        assert session.scalars(text("SELECT tone FROM public.assistants")).all() == [payload()["tone"]]


def test_api_commit_and_cross_owner_denial(corpus):
    factory, owners, ids = corpus
    app = create_app()
    app.state.session_factory = factory
    app.dependency_overrides[get_current_owner] = lambda: OwnerContext(owners[0])
    client = TestClient(app)
    assert client.patch(f"/assistants/{ids[0]}", json={"tone": "formal"}).status_code == 200
    assert client.get(f"/assistants/{ids[1]}").status_code == 404
    assert client.patch(f"/assistants/{ids[1]}", json={"tone": "wrong"}).status_code == 404
    with factory.begin() as session:
        set_owner_identity(session, owners[0])
        assert session.scalar(text("SELECT tone FROM public.assistants WHERE id=:id"), {"id": ids[0]}) == "formal"


def test_data_api_grants_absent(postgres):
    admin, _ = postgres
    with admin.connect() as conn:
        for role in ("anon", "authenticated"):
            assert conn.scalar(text("SELECT EXISTS (SELECT FROM pg_roles WHERE rolname=:role)"), {"role": role}), "Provision local stand-in Data API roles"
            for permission in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert not conn.scalar(text("SELECT has_table_privilege(:role,'public.assistants',:permission)"), {"role": role, "permission": permission})
            for permission in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                assert not conn.scalar(text("SELECT has_any_column_privilege(:role,'public.assistants',:permission)"), {"role": role, "permission": permission})
