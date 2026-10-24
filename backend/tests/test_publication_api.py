from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from assistant_builder.auth import OwnerContext, get_current_owner
from assistant_builder.main import create_app
from assistant_builder.publication import PublicationFailure
from assistant_builder.publication_api import get_publication_service, _widget_origin


class FakePublicationService:
    def __init__(self, owner, assistant):
        self.owner, self.assistant = owner, assistant
        self.status_result = {
            "published": False, "public_id": None, "version": None, "published_at": None,
            "draft_fingerprint": "a" * 64, "has_changes": True, "readiness": "fallback_only",
        }
        self.failure = None
        self.publish_args = None
        self.replayed = False

    def _check(self, owner, assistant):
        if self.failure:
            raise self.failure
        if (owner, assistant) != (self.owner, self.assistant):
            raise PublicationFailure("not_found")

    def status(self, owner, assistant):
        self._check(owner, assistant)
        return self.status_result

    def publish(self, owner, assistant, **kwargs):
        self._check(owner, assistant)
        self.publish_args = kwargs
        publication = SimpleNamespace(public_id=uuid4())
        snapshot = SimpleNamespace(version=1, activated_at=datetime.now(timezone.utc),
                                   draft_fingerprint=kwargs["expected_fingerprint"])
        return publication, snapshot, self.replayed

    def get_active_publication(self, owner, assistant):
        self._check(owner, assistant)
        return SimpleNamespace(public_id=uuid4())


@pytest.fixture
def publication_client(monkeypatch):
    owner, assistant = uuid4(), uuid4()
    workflow = FakePublicationService(owner, assistant)
    app = create_app()
    app.dependency_overrides[get_current_owner] = lambda: OwnerContext(owner)
    app.dependency_overrides[get_publication_service] = lambda: workflow
    monkeypatch.setattr("assistant_builder.publication_api.get_settings", lambda: SimpleNamespace(
        widget_asset_origin="https://assets.example.test"))
    with TestClient(app) as client:
        yield client, workflow, owner, assistant
    app.dependency_overrides.clear()


def test_status_is_authenticated_owner_scoped_uncached(publication_client):
    client, _, _, assistant = publication_client
    response = client.get(f"/assistants/{assistant}/publication")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["readiness"] == "fallback_only"
    assert response.json()["public_id"] is None


def test_publish_uses_only_server_owner_and_contract_fingerprint(publication_client):
    client, workflow, owner, assistant = publication_client
    response = client.post(f"/assistants/{assistant}/publication",
        headers={"Idempotency-Key": "publish-1"},
        json={"expected_draft_fingerprint": "a" * 64, "expected_published_version": None})
    assert response.status_code == 201
    assert response.json()["version"] == 1
    assert response.json()["replayed"] is False
    assert workflow.publish_args == {
        "expected_fingerprint": "a" * 64, "expected_version": None, "idempotency_key": "publish-1"}
    assert "owner_id" not in response.json()


def test_idempotent_publish_replay_returns_200(publication_client):
    client, workflow, _, assistant = publication_client
    workflow.replayed = True
    response = client.post(f"/assistants/{assistant}/publication",
        headers={"Idempotency-Key": "publish-replay"},
        json={"expected_draft_fingerprint": "a" * 64, "expected_published_version": None})
    assert response.status_code == 200
    assert response.json()["replayed"] is True


@pytest.mark.parametrize("payload", [
    {"expected_draft_fingerprint": "bad", "expected_published_version": None},
    {"expected_draft_fingerprint": "a" * 64, "expected_published_version": None, "owner_id": str(uuid4())},
    {"expected_draft_fingerprint": "a" * 64, "expected_published_version": 0},
])
def test_publish_rejects_invalid_or_untrusted_input(publication_client, payload):
    client, workflow, _, assistant = publication_client
    response = client.post(f"/assistants/{assistant}/publication",
        headers={"Idempotency-Key": "publish-2"}, json=payload)
    assert response.status_code == 422
    assert workflow.publish_args is None


def test_conflicts_are_safe_and_owner_miss_is_not_found(publication_client):
    client, workflow, _, assistant = publication_client
    workflow.failure = PublicationFailure("draft_changed")
    response = client.post(f"/assistants/{assistant}/publication",
        headers={"Idempotency-Key": "publish-3"},
        json={"expected_draft_fingerprint": "a" * 64, "expected_published_version": None})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "draft_changed"
    workflow.failure = PublicationFailure("not_found")
    assert client.get(f"/assistants/{assistant}/publication").status_code == 404


def test_embed_snippet_contains_only_opaque_id_and_configured_asset_origin(publication_client):
    client, _, _, assistant = publication_client
    response = client.get(f"/assistants/{assistant}/embed")
    assert response.status_code == 200
    body = response.json()
    assert body["public_id"] in body["snippet"]
    assert body["snippet"] == (f'<script async src="https://assets.example.test/widget.js" '
                                f'data-assistant-id="{body["public_id"]}"></script>')
    assert "owner_id" not in body and "model" not in body
    assert response.headers["cache-control"] == "no-store"


def test_missing_and_unsafe_widget_origins_fail_closed():
    with pytest.raises(PublicationFailure, match="publication_unavailable"):
        _widget_origin(None)
    for value in ("javascript:alert(1)", "https://good.test/path", "https://user:pass@good.test",
                  "https://good.test?x=1", "http://public.example.test"):
        with pytest.raises(PublicationFailure, match="publication_unavailable"):
            _widget_origin(value)
    assert _widget_origin("http://localhost:4173/") == "http://localhost:4173"


def test_publication_routes_require_authentication():
    app = create_app()
    response = TestClient(app).get(f"/assistants/{uuid4()}/publication")
    assert response.status_code == 401
