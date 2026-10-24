from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from assistant_builder.auth import OwnerContext, get_current_owner
from assistant_builder.conversation_history import ConversationHistoryNotFound, ConversationHistoryUnavailable, InvalidHistoryCursor
from assistant_builder.conversation_history_api import get_history_service
from assistant_builder.main import create_app


@pytest.fixture
def history_client():
    owner, assistant, conversation = uuid4(), uuid4(), uuid4()

    class FakeHistory:
        def list_conversations(self, requested_owner, requested_assistant, *, limit, cursor=None):
            assert (requested_owner, requested_assistant) == (owner, assistant)
            if cursor == "cross-owner":
                raise ConversationHistoryNotFound
            if cursor == "bad-cursor":
                raise InvalidHistoryCursor
            if cursor == "database-error":
                raise ConversationHistoryUnavailable
            return {"items": [{"conversation_id": conversation, "created_at": datetime.now(timezone.utc),
                "last_activity_at": None, "latest_status": "idle",
                "latest_outcome": None, "latest_published_version": None}],
                "next_cursor": None, "limit": limit}

        def get_conversation(self, requested_owner, requested_assistant, requested_conversation, *, limit, cursor=None):
            assert (requested_owner, requested_assistant, requested_conversation) == (owner, assistant, conversation)
            if cursor == "cross-owner":
                raise ConversationHistoryNotFound
            if cursor == "database-error":
                raise ConversationHistoryUnavailable
            return {"conversation_id": conversation, "created_at": datetime.now(timezone.utc), "limit": limit,
                "next_cursor": None, "turns": [{"user_message": "question",
                    "user_created_at": datetime.now(timezone.utc), "assistant_message": None,
                    "assistant_created_at": None, "status": "uncertain", "outcome": None,
                    "published_version": 3}]}

    app = create_app()
    app.dependency_overrides[get_current_owner] = lambda: OwnerContext(owner)
    app.dependency_overrides[get_history_service] = lambda: FakeHistory()
    with TestClient(app) as client:
        yield client, assistant, conversation
    app.dependency_overrides.clear()


def test_owner_history_list_is_bounded_and_projects_safe_fields(history_client):
    client, assistant, conversation = history_client
    response = client.get(f"/assistants/{assistant}/conversations?limit=20")
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["conversation_id"] == str(conversation)
    assert body["items"][0]["latest_status"] == "idle"
    assert not {"owner_id", "token_sha256", "error_code", "snapshot_id"} & body["items"][0].keys()
    assert client.get(f"/assistants/{assistant}/conversations?limit=101").status_code == 422
    assert client.get(f"/assistants/{assistant}/conversations?limit=0").status_code == 422


def test_owner_history_detail_hides_internal_failure_metadata(history_client):
    client, assistant, conversation = history_client
    response = client.get(f"/assistants/{assistant}/conversations/{conversation}")
    assert response.status_code == 200
    body = response.json()
    assert body["turns"][0]["status"] == "uncertain"
    assert body["turns"][0]["assistant_message"] is None
    assert body["turns"][0]["published_version"] == 3
    for forbidden in ("owner_id", "token_sha256", "input_sha256", "error_code", "snapshot_id", "request_id"):
        assert forbidden not in response.text


def test_cross_owner_or_cross_conversation_history_is_hidden(history_client):
    client, assistant, conversation = history_client
    list_response = client.get(f"/assistants/{assistant}/conversations?cursor=cross-owner")
    detail_response = client.get(f"/assistants/{assistant}/conversations/{conversation}?cursor=cross-owner")
    assert list_response.status_code == detail_response.status_code == 404
    assert list_response.json()["detail"] == detail_response.json()["detail"] == "Assistant or conversation not found"


def test_invalid_cursor_and_storage_failure_are_safe(history_client):
    client, assistant, conversation = history_client
    invalid = client.get(f"/assistants/{assistant}/conversations?cursor=bad-cursor")
    unavailable = client.get(f"/assistants/{assistant}/conversations/{conversation}?cursor=database-error")
    assert invalid.status_code == 422
    assert unavailable.status_code == 503
    assert "error" not in unavailable.text.lower()
