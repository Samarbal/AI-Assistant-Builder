import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from assistant_builder.generation import Answer
from assistant_builder.main import create_app
from assistant_builder.public_chat import PublicChatFailure, PublicDemoGate, PublicRequestGuard, PublicChatService
from assistant_builder.public_api import router as public_router


def test_demo_gate_is_disabled_by_default_and_accepts_only_configured_digest():
    gate = PublicDemoGate(False, None)
    with pytest.raises(PublicChatFailure, match="public_chat_disabled"):
        gate.check("any-token")
    token = "demo-secret-that-is-long-enough"
    gate = PublicDemoGate(True, sha256(token.encode()).hexdigest())
    gate.check(token)
    with pytest.raises(PublicChatFailure, match="demo_access_denied"):
        gate.check(token + "x")


def test_demo_gate_rejects_more_than_two_or_malformed_hashes():
    with pytest.raises(ValueError):
        PublicDemoGate(True, ",".join(["a" * 64] * 3))
    with pytest.raises(ValueError):
        PublicDemoGate(True, "not-a-digest")


def test_public_answer_returns_exact_fallback_without_provider_for_empty_published_set():
    class NeverEmbedding:
        async def embed(self, texts):
            raise AssertionError("empty published set must not embed")
    class NeverGenerator:
        async def generate(self, *args):
            raise AssertionError("fallback-only publication must not generate")
    service = PublicChatService(None, NeverEmbedding(), NeverGenerator(), PublicRequestGuard())
    assistant = SimpleNamespace(config={"role": "support", "tone": "warm", "response_style": "short",
        "fallback_message": "Exact fallback."}, source_count=0)
    result = asyncio.run(service._answer(assistant, "question"))
    assert result == Answer("Exact fallback.", "fallback")


def test_public_message_rejects_utf8_question_over_limit_before_database_or_provider():
    class NeverSessions:
        def begin(self):
            raise AssertionError("invalid input must be rejected before database work")
    service = PublicChatService(NeverSessions(), None, None, PublicRequestGuard())
    with pytest.raises(PublicChatFailure, match="invalid_request"):
        asyncio.run(service.message(uuid4(), uuid4(), "visitor-capability", "ع" * 501, uuid4()))


def test_disabled_public_chat_route_fails_closed(monkeypatch):
    monkeypatch.setenv("PUBLIC_CHAT_ENABLED", "false")
    # Settings are evaluated by create_app; no database or provider is needed.
    app = create_app()
    with TestClient(app) as client:
        response = client.get(f"/public/assistants/{uuid4()}")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "public_chat_disabled"
    assert "owner_id" not in response.text and "snapshot" not in response.text


def test_public_http_contract_requires_demo_gate_and_uses_public_projection():
    token = "authorized-demo-token-value"
    public_id, conversation_id, message_id = uuid4(), uuid4(), uuid4()
    class FakeService:
        guard = PublicRequestGuard()
        def public_details(self, requested_id):
            assert requested_id == public_id
            return {"name": "Demo assistant", "colors": {"primary": "#123456"}, "version": 2}
        def create_conversation(self, requested_id):
            assert requested_id == public_id
            return {"conversation_id": conversation_id, "conversation_token": "v" * 43,
                    "expires_at": datetime(2026, 10, 24, tzinfo=timezone.utc)}
        async def message(self, requested_public_id, requested_conversation_id, visitor_token, message, request_id):
            assert requested_public_id == public_id and requested_conversation_id == conversation_id
            assert visitor_token == "v" * 43 and message == "hello"
            return {"message_id": message_id, "answer": "safe answer", "outcome": "grounded",
                    "created_at": datetime(2026, 10, 23, tzinfo=timezone.utc), "version": 2}
    app = FastAPI()
    app.include_router(public_router)
    app.state.public_demo_gate = PublicDemoGate(True, sha256(token.encode()).hexdigest())
    app.state.public_chat_service = FakeService()
    with TestClient(app) as client:
        denied = client.get(f"/public/assistants/{public_id}")
        assert denied.status_code == 404
        headers = {"X-Demo-Access": token}
        details = client.get(f"/public/assistants/{public_id}", headers=headers)
        assert details.status_code == 200 and details.headers["cache-control"] == "no-store"
        assert details.json() == {"name": "Demo assistant", "colors": {"primary": "#123456"}, "version": 2}
        conversation = client.post(f"/public/assistants/{public_id}/conversations",
            headers=headers, json={})
        assert conversation.status_code == 201
        assert "owner_id" not in conversation.text and "token_sha256" not in conversation.text
        result = client.post(f"/public/assistants/{public_id}/conversations/{conversation_id}/messages",
            headers={**headers, "X-Visitor-Token": "v" * 43},
            json={"message": "hello", "request_id": str(uuid4())})
        assert result.status_code == 200 and "citations" not in result.json(), result.text
        assert "private" not in result.text and "owner_id" not in result.text


def test_public_guard_rate_limit_is_scoped_and_bounded():
    async def run():
        clock = [0.0]
        guard = PublicRequestGuard(rate=1, key_capacity=1, clock=lambda: clock[0])
        public_id = uuid4()
        await guard.check_rate("127.0.0.1", public_id)
        with pytest.raises(PublicChatFailure, match="rate_limited"):
            await guard.check_rate("127.0.0.1", public_id)
        with pytest.raises(PublicChatFailure, match="rate_limited"):
            await guard.check_rate("127.0.0.2", uuid4())
        clock[0] = 61.0
        await guard.check_rate("127.0.0.1", public_id)
    asyncio.run(run())


def test_public_guard_allows_only_one_inflight_turn_per_conversation():
    guard = PublicRequestGuard()
    conversation = uuid4()
    guard.acquire_conversation(conversation)
    with pytest.raises(PublicChatFailure, match="request_in_progress"):
        guard.acquire_conversation(conversation)
    guard.release_conversation(conversation)


def test_public_guard_rejects_saturated_concurrency_before_acquiring_slot():
    async def run():
        guard = PublicRequestGuard(global_limit=1, per_assistant=1)
        assistant = uuid4()
        async with guard.slot(assistant):
            with pytest.raises(PublicChatFailure, match="concurrency_limited"):
                async with guard.slot(assistant):
                    pass
    asyncio.run(run())
