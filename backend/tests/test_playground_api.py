from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from assistant_builder.auth import OwnerContext, get_current_owner
from assistant_builder.generation import Answer, Citation
from assistant_builder.main import create_app
from assistant_builder.playground_api import get_rag_orchestrator
from assistant_builder.rag import RagFailure


class FakeRag:
    def __init__(self, answer=None, failure=None):
        self.answer_value, self.failure, self.calls = answer, failure, []

    async def answer(self, owner_id, assistant_id, question):
        self.calls.append((owner_id, assistant_id, question))
        if self.failure:
            raise self.failure
        return self.answer_value


@pytest.fixture
def playground():
    owner, other = uuid4(), uuid4()
    assistant, file_id, chunk_id = uuid4(), uuid4(), uuid4()
    answer = Answer("Returns are accepted within 14 days.", "grounded", (
        Citation(file_id, chunk_id, "policy.pdf", "Returns are accepted within 14 days."),
    ))
    rag = FakeRag(answer)
    app = create_app()
    app.dependency_overrides[get_current_owner] = lambda: OwnerContext(owner)
    app.dependency_overrides[get_rag_orchestrator] = lambda: rag
    with TestClient(app) as client:
        yield client, app, rag, owner, other, assistant, file_id, chunk_id
    app.dependency_overrides.clear()


def test_authenticated_message_returns_answer_and_server_citation(playground):
    client, _, rag, owner, _, assistant, file_id, chunk_id = playground
    response = client.post(f"/assistants/{assistant}/playground/messages",
                           json={"message": "How long are returns?"})
    assert response.status_code == 200
    assert response.json() == {
        "answer": "Returns are accepted within 14 days.", "outcome": "grounded",
        "citations": [{"file_id": str(file_id), "chunk_id": str(chunk_id),
                       "filename": "policy.pdf", "excerpt": "Returns are accepted within 14 days."}],
    }
    assert response.headers["cache-control"] == "no-store"
    assert rag.calls == [(owner, assistant, "How long are returns?")]


def test_exact_fallback_has_empty_citations(playground):
    client, _, rag, _, _, assistant, *_ = playground
    rag.answer_value = Answer("الرد الاحتياطي كما هو.", "fallback")
    response = client.post(f"/assistants/{assistant}/playground/messages", json={"message": "سؤال؟"})
    assert response.status_code == 200
    assert response.json() == {"answer": "الرد الاحتياطي كما هو.", "outcome": "fallback", "citations": []}


@pytest.mark.parametrize("body", [
    {}, {"message": "   "}, {"message": "x" * 4001},
    {"message": "hello", "owner_id": str(uuid4())},
])
def test_invalid_body_is_rejected_before_rag(body, playground):
    client, _, rag, _, _, assistant, *_ = playground
    response = client.post(f"/assistants/{assistant}/playground/messages", json=body)
    assert response.status_code == 422
    assert rag.calls == []


def test_provider_failure_is_safe_503_with_configured_fallback(playground):
    client, _, rag, _, _, assistant, *_ = playground
    rag.failure = RagFailure("generation_rate_limited", "Use the configured fallback exactly.")
    response = client.post(f"/assistants/{assistant}/playground/messages", json={"message": "question"})
    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "generation_rate_limited",
                   "message": "Playground could not complete this request. Please retry."},
        "fallback_message": "Use the configured fallback exactly.",
    }
    assert "private" not in response.text


def test_diagnostic_generation_code_is_safe_and_does_not_become_fallback(playground):
    client, _, rag, _, _, assistant, *_ = playground
    rag.failure = RagFailure("generation_output_invalid_citation", "configured fallback")
    response = client.post(f"/assistants/{assistant}/playground/messages", json={"message": "question"})
    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "generation_output_invalid_citation",
            "message": "Playground could not complete this request. Please retry.",
        },
        "fallback_message": "configured fallback",
    }


def test_cross_owner_access_is_404_and_no_retrieval_call(playground):
    client, app, rag, _, other, assistant, *_ = playground
    app.dependency_overrides[get_current_owner] = lambda: OwnerContext(other)
    # The RAG service's owner-scoped lookup rejects this before reaching Retriever.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from assistant_builder.models import Assistant, Base
    from assistant_builder.rag import RagOrchestrator

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add(Assistant(id=assistant, owner_id=uuid4(), name="private", role="support",
            colors={}, response_style="short", tone="friendly", fallback_message="unknown"))

    class Never:
        async def retrieve(self, *args, **kwargs):
            pytest.fail("cross-owner assistant must be rejected before retrieval")

    class NeverGenerate:
        async def generate(self, *args, **kwargs):
            pytest.fail("cross-owner assistant must be rejected before generation")

    app.dependency_overrides[get_rag_orchestrator] = lambda: RagOrchestrator(sessions, Never(), NeverGenerate())
    response = client.post(f"/assistants/{assistant}/playground/messages", json={"message": "question"})
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "assistant_not_found"
    assert rag.calls == []
    engine.dispose()


def test_missing_authentication_is_rejected(playground):
    client, app, rag, *_ = playground
    app.dependency_overrides.pop(get_current_owner)
    response = client.post(f"/assistants/{uuid4()}/playground/messages", json={"message": "hello"})
    assert response.status_code == 401
    assert rag.calls == []


def test_unconfigured_rag_returns_safe_503(playground):
    client, app, rag, _, _, assistant, *_ = playground
    app.dependency_overrides.pop(get_rag_orchestrator)
    response = client.post(f"/assistants/{assistant}/playground/messages", json={"message": "hello"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "playground_unavailable"
    assert rag.calls == []
