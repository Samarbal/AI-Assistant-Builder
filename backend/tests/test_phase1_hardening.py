from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from assistant_builder.auth import SupabaseAuthVerifier, OwnerContext, get_current_owner
from assistant_builder.main import create_app
from assistant_builder.models import Base, Assistant
from .test_phase1_contracts import OWNER_A, payload, make_client


@pytest.mark.parametrize("field", list(payload()))
def test_patch_rejects_null(field):
    client, _, repository = make_client()
    created = client.post("/assistants", json=payload()).json()
    assert client.patch(f"/assistants/{created['id']}", json={field: None}).status_code == 422
    assert repository.items[0].name == payload()["name"]


@pytest.mark.parametrize("upstream,body,expected", [
    (401, {}, 401), (403, {}, 401), (429, {}, 503), (500, {}, 503),
    (200, {}, 503), (200, {"id": None}, 503), (200, {"id": "invalid"}, 503),
])
def test_auth_status_classification(upstream, body, expected):
    client, app, _ = make_client()
    app.dependency_overrides.pop(get_current_owner)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(upstream, json=body))) as http:
        app.state.auth_verifier = SupabaseAuthVerifier("https://example.test", "test", http)
        response = client.get("/assistants", headers={"Authorization": "Bearer test"})
    assert response.status_code == expected
    if expected == 401:
        assert response.headers["www-authenticate"] == "Bearer"


def test_auth_timeout_is_service_unavailable():
    client, app, _ = make_client()
    app.dependency_overrides.pop(get_current_owner)
    def timeout(request):
        raise httpx.ReadTimeout("private upstream detail", request=request)
    with httpx.Client(transport=httpx.MockTransport(timeout)) as http:
        app.state.auth_verifier = SupabaseAuthVerifier("https://example.test", "test", http)
        response = client.get("/assistants", headers={"Authorization": "Bearer test"})
    assert response.status_code == 503
    assert "private" not in response.text


def test_real_session_commit_update_and_rollback():
    # SQLite verifies transaction lifecycle only, never PostgreSQL/RLS behavior.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    app = create_app()
    app.state.session_factory = factory
    app.dependency_overrides[get_current_owner] = lambda: OwnerContext(OWNER_A)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.post("/assistants", json=payload())
        assert response.status_code == 201
        identifier = response.json()["id"]
        assert client.patch(f"/assistants/{identifier}", json={"tone": "formal"}).status_code == 200
        with factory() as session:
            assert session.scalar(select(Assistant)).tone == "formal"
        from sqlalchemy import event
        def fail_commit(session):
            raise RuntimeError("commit failed")
        event.listen(factory, "before_commit", fail_commit)
        assert client.post("/assistants", json=payload("Must rollback")).status_code == 500
        event.remove(factory, "before_commit", fail_commit)
        with factory() as session:
            assert len(session.scalars(select(Assistant)).all()) == 1
    finally:
        engine.dispose()


def test_engine_created_once_and_disposed(monkeypatch):
    from assistant_builder import main
    engine = MagicMock()
    create = MagicMock(return_value=engine)
    monkeypatch.setattr(main, "create_database_engine", create)
    monkeypatch.setattr(main, "get_settings", lambda: type("Settings", (), {
        "database_url": "configured", "app_name": "test", "supabase_url": None,
        "supabase_anon_key": None,
    })())
    app = main.create_app()
    with TestClient(app) as client:
        factory = app.state.session_factory
        client.get("/assistants")
        client.get("/assistants")
        assert factory is app.state.session_factory
        create.assert_called_once()
    engine.dispose.assert_called_once()
