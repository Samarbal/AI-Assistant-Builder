from uuid import UUID, uuid4

import httpx
from fastapi.testclient import TestClient

from assistant_builder.api import get_assistant_service
from assistant_builder.auth import SupabaseAuthVerifier, get_current_owner
from assistant_builder.main import create_app
from assistant_builder.services import AssistantNotFound


OWNER_A = UUID("00000000-0000-0000-0000-000000000001")
OWNER_B = UUID("00000000-0000-0000-0000-000000000002")


class FakeAssistant:
    def __init__(self, owner_id: UUID, data: dict):
        self.id = uuid4()
        self.owner_id = owner_id
        self.name = data["name"]
        self.role = data["role"]
        self.colors = data["colors"]
        self.response_style = data["response_style"]
        self.tone = data["tone"]
        self.fallback_message = data["fallback_message"]
        self.state = "draft"
        from datetime import datetime, timezone

        self.created_at = datetime.now(timezone.utc)
        self.updated_at = self.created_at


class FakeRepository:
    def __init__(self):
        self.items: list[FakeAssistant] = []

    def create(self, owner_id, data):
        assistant = FakeAssistant(owner_id, data.model_dump())
        self.items.append(assistant)
        return assistant

    def list_for_owner(self, owner_id):
        return [item for item in self.items if item.owner_id == owner_id]

    def get_for_owner(self, owner_id, assistant_id):
        return next((item for item in self.items if item.owner_id == owner_id and item.id == assistant_id), None)

    def update(self, assistant, data):
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(assistant, field, value)
        return assistant


def make_client():
    app = create_app()
    repository = FakeRepository()

    def current_owner():
        return type("Owner", (), {"owner_id": OWNER_A})()

    def service():
        from assistant_builder.services import AssistantService

        return AssistantService(repository)

    app.dependency_overrides[get_current_owner] = current_owner
    app.dependency_overrides[get_assistant_service] = service
    return TestClient(app), app, repository


def payload(name="Support"):
    return {
        "name": name,
        "role": "Customer support assistant",
        "colors": {"primary": "#123456"},
        "response_style": "concise",
        "tone": "friendly",
        "fallback_message": "I cannot find that answer in the provided information.",
    }


def test_create_assistant_derives_owner_and_starts_draft():
    client, app, _ = make_client()
    response = client.post("/assistants", json=payload())

    assert response.status_code == 201
    body = response.json()
    assert body["owner_id"] == str(OWNER_A)
    assert body["state"] == "draft"
    app.dependency_overrides.clear()


def test_owner_can_list_and_update_only_owned_assistants():
    client, app, repository = make_client()
    own = repository.create(OWNER_A, type("Create", (), {"model_dump": lambda self: payload("Own")})())
    other = repository.create(OWNER_B, type("Create", (), {"model_dump": lambda self: payload("Other")})())

    listed = client.get("/assistants")
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["Own"]

    updated = client.patch(f"/assistants/{own.id}", json={"tone": "formal"})
    assert updated.status_code == 200
    assert updated.json()["tone"] == "formal"

    hidden = client.get(f"/assistants/{other.id}")
    assert hidden.status_code == 404
    app.dependency_overrides.clear()


def test_client_cannot_supply_owner_id():
    client, app, _ = make_client()
    body = payload()
    body["owner_id"] = str(OWNER_B)

    response = client.post("/assistants", json=body)

    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_missing_authentication_is_rejected():
    client, app, _ = make_client()
    app.dependency_overrides.pop(get_current_owner)

    response = client.get("/assistants")

    assert response.status_code == 401
    app.dependency_overrides.clear()


def test_supabase_auth_verifier_derives_owner_from_authenticated_user():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://supabase.example.test/auth/v1/user"
        assert request.headers["authorization"] == "Bearer access-token"
        assert request.headers["apikey"] == "publishable-key"
        return httpx.Response(200, json={"id": str(OWNER_A)}, request=request)

    verifier = SupabaseAuthVerifier(
        "https://supabase.example.test",
        "publishable-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    context = verifier.verify("Bearer access-token")

    assert context.owner_id == OWNER_A
