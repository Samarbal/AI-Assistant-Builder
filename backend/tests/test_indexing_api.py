from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from assistant_builder.auth import OwnerContext, get_current_owner
from assistant_builder.indexing import IndexStatus, IndexingFailure, PreparationStatus
from assistant_builder.indexing_api import get_indexing_service
from assistant_builder.main import create_app


class FakeIndexing:
    def __init__(self, owner, assistant):
        self.owner, self.assistant = owner, assistant
        self.started, self.advanced, self.status_calls = [], [], []
        self.current = PreparationStatus("needs_preparation", None, 0, 0, 2)
        self.fail = None

    def status(self, owner, assistant):
        self.status_calls.append((owner, assistant))
        if owner != self.owner or assistant != self.assistant:
            raise IndexingFailure("assistant_not_found")
        if self.fail:
            raise self.fail
        return self.current

    def start(self, owner, assistant, key):
        self.started.append((owner, assistant, key))
        if owner != self.owner or assistant != self.assistant:
            raise IndexingFailure("assistant_not_found")
        return IndexStatus(self.assistant, "building", 0, 2, 0)

    async def advance(self, owner, assistant, index_id, *, idempotency_key=None):
        self.advanced.append((owner, assistant, index_id, idempotency_key))
        if owner != self.owner or assistant != self.assistant or index_id != self.assistant:
            raise IndexingFailure("index_not_found")
        self.current = PreparationStatus("preparing", index_id, 1, 2, 2)
        return IndexStatus(index_id, "building", 1, 2, 1)


@pytest.fixture
def indexing_client():
    owner, assistant = uuid4(), uuid4()
    workflow = FakeIndexing(owner, assistant)
    app = create_app()
    app.dependency_overrides[get_current_owner] = lambda: OwnerContext(owner)
    app.dependency_overrides[get_indexing_service] = lambda: workflow
    with TestClient(app) as client:
        yield client, workflow, owner, assistant
    app.dependency_overrides.clear()


def test_status_is_owner_scoped_and_not_cached(indexing_client):
    client, workflow, owner, assistant = indexing_client
    response = client.get(f"/assistants/{assistant}/playground/status")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "readiness": "needs_preparation", "operation_id": None,
        "completed_chunks": 0, "total_chunks": 0, "eligible_files": 2,
        "next_action": "prepare", "reason": None,
    }
    assert workflow.status_calls == [(owner, assistant)]


def test_prepare_runs_one_bounded_batch_and_returns_progress(indexing_client):
    client, workflow, owner, assistant = indexing_client
    key = uuid4()
    response = client.post(f"/assistants/{assistant}/playground/prepare", json={},
                           headers={"Idempotency-Key": str(key)})
    assert response.status_code == 202
    assert response.json()["readiness"] == "preparing"
    assert response.json()["completed_chunks"] == 1
    assert workflow.started == [(owner, assistant, key)]
    assert workflow.advanced == [(owner, assistant, assistant, key)]


def test_continue_passes_operation_and_new_batch_idempotency_key(indexing_client):
    client, workflow, owner, assistant = indexing_client
    key = uuid4()
    response = client.post(f"/assistants/{assistant}/playground/prepare",
        json={"operation_id": str(assistant)}, headers={"Idempotency-Key": str(key)})
    assert response.status_code == 202
    assert workflow.started == []
    assert workflow.advanced == [(owner, assistant, assistant, key)]


@pytest.mark.parametrize("payload,headers", [
    ({}, {}), ({"owner_id": str(uuid4())}, {"Idempotency-Key": str(uuid4())}),
])
def test_prepare_rejects_missing_idempotency_or_untrusted_fields(indexing_client, payload, headers):
    client, workflow, _, assistant = indexing_client
    response = client.post(f"/assistants/{assistant}/playground/prepare", json=payload, headers=headers)
    assert response.status_code == 422
    assert workflow.started == [] and workflow.advanced == []


def test_wrong_owner_uses_same_not_found_response(indexing_client):
    client, workflow, _, assistant = indexing_client
    workflow.fail = IndexingFailure("assistant_not_found")
    response = client.get(f"/assistants/{assistant}/playground/status")
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "assistant_not_found", "message": "Assistant not found."}}


def test_authentication_is_required_before_status_access():
    app = create_app()
    response = TestClient(app).get(f"/assistants/{uuid4()}/playground/status")
    assert response.status_code == 401


def test_provider_failure_is_safe_and_contains_no_raw_error(indexing_client):
    client, workflow, _, assistant = indexing_client
    workflow.fail = IndexingFailure("embedding_provider_failure")
    response = client.get(f"/assistants/{assistant}/playground/status")
    assert response.status_code == 503
    assert response.json() == {"detail": {
        "code": "embedding_provider_failure",
        "message": "The embedding service could not complete this batch. Review status before retrying.",
    }}
    assert "raw" not in response.text


def test_uncertain_provider_attempt_is_not_retryable_from_owner_api(indexing_client):
    client, workflow, _, assistant = indexing_client
    workflow.current = PreparationStatus("failed", assistant, 1, 2, 2, "provider_attempt_uncertain")
    response = client.get(f"/assistants/{assistant}/playground/status")
    assert response.status_code == 200
    assert response.json()["next_action"] is None
    assert "operator review" in response.json()["reason"]
