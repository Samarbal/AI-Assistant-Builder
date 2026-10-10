"""PostgreSQL checks. Never print DSNs or assume Supabase JWT context."""
import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import sessionmaker

from assistant_builder.auth import OwnerContext, get_current_owner
from assistant_builder.config import get_settings
from assistant_builder.main import create_app
from assistant_builder.models import Assistant
from .test_phase1_contracts import payload


def connect_engine(url):
    engine = create_engine(url, connect_args={"connect_timeout": 5}, hide_parameters=True)
    unavailable = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        engine.dispose()
        unavailable = True
    if unavailable:
        pytest.fail("Configured PostgreSQL connection unavailable; connection details suppressed", pytrace=False)
    return engine


def test_configured_runtime_role_rls_prerequisites():
    url = get_settings().database_url
    if not url:
        pytest.skip("DATABASE_URL unavailable: runtime role audit blocked")
    engine = connect_engine(url)
    try:
        with engine.connect() as conn:
            role = conn.execute(text("""
                SELECT r.rolsuper, r.rolbypassrls,
                       pg_has_role(current_user, c.relowner, 'USAGE') AS owns_table,
                       c.relrowsecurity, c.relforcerowsecurity
                FROM pg_roles r CROSS JOIN pg_class c
                WHERE r.rolname = current_user AND c.oid = to_regclass('public.assistants')
            """)).mappings().one_or_none()
            assert role is not None, "Runtime assistants table unavailable"
            assert not role["rolsuper"], "Runtime role is superuser: RLS bypass"
            assert not role["rolbypassrls"], "Runtime role has BYPASSRLS"
            assert role["relrowsecurity"], "RLS is not enabled"
            assert not role["owns_table"] or role["relforcerowsecurity"], "Table owner bypasses RLS"
            assert conn.scalar(text("SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename='assistants'")), "No assistant policies"
    finally:
        engine.dispose()


def test_postgresql_persistence_and_application_owner_isolation():
    url = os.getenv("PHASE1_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PHASE1_TEST_DATABASE_URL absent: requires a dedicated migrated test database")
    expected_role = os.getenv("PHASE1_TEST_RUNTIME_ROLE")
    if not expected_role:
        pytest.skip("PHASE1_TEST_RUNTIME_ROLE absent: explicitly identify runtime-equivalent role")
    engine = connect_engine(url)
    factory = sessionmaker(engine, expire_on_commit=False)
    owner_a, owner_b = uuid4(), uuid4()
    current_owner = [owner_a]
    app = create_app()
    app.state.session_factory = factory
    app.dependency_overrides[get_current_owner] = lambda: OwnerContext(current_owner[0])
    client = TestClient(app)
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT current_user")) == expected_role
        created = client.post("/assistants", json=payload())
        assert created.status_code == 201
        identifier = created.json()["id"]
        assert client.patch(f"/assistants/{identifier}", json={"tone": "formal"}).status_code == 200
        with factory() as session:
            assert session.scalar(select(Assistant).where(Assistant.id == UUID(identifier))).tone == "formal"
        current_owner[0] = owner_b
        assert client.get("/assistants").json() == []
        assert client.get(f"/assistants/{identifier}").status_code == 404
        assert client.patch(f"/assistants/{identifier}", json={"tone": "changed"}).status_code == 404
        current_owner[0] = owner_a
        assert client.get(f"/assistants/{identifier}").json()["tone"] == "formal"
    finally:
        with factory.begin() as session:
            session.execute(delete(Assistant).where(Assistant.owner_id.in_([owner_a, owner_b])))
        engine.dispose()
