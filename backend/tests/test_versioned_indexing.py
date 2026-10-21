from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from assistant_builder.chunking import ChunkingConfig, DeterministicChunker
from assistant_builder.embeddings import EmbeddingFailure, EmbeddingResult
from assistant_builder.indexing import (
    IndexingFailure, VersionedIndexService, split_embedding_batches,
)
import assistant_builder.indexing as indexing_module
from assistant_builder.knowledge_repository import KnowledgeRepository
from assistant_builder.models import (
    Assistant, Base, KnowledgeChunk, KnowledgeFile, KnowledgeFileText, KnowledgeIndex,
    KnowledgeIndexBatch,
)
from .test_phase1_contracts import payload


class CharTokenizer:
    fingerprint = "test-char-v1"

    def encode(self, text):
        return [ord(char) for char in text]

    def offsets(self, tokens, text):
        return list(range(len(text) + 1))


class FakeEmbeddings:
    def __init__(self, *, failure=None, bad=None, fail_on_call=None):
        self.calls = []
        self.failure, self.bad, self.fail_on_call = failure, bad, fail_on_call

    async def embed(self, texts):
        self.calls.append(texts)
        if self.failure or self.fail_on_call == len(self.calls):
            if self.failure:
                raise self.failure
            raise EmbeddingFailure("embedding_quota_or_rate_limited")
        vectors = []
        for i, _ in enumerate(texts):
            vector = [0.0] * 768
            vector[i % 768] = 1.0
            vectors.append(tuple(vector))
        if self.bad == "dimension":
            vectors[0] = (1.0,)
        if self.bad == "nan":
            vectors[0] = (float("nan"),) + (0.0,) * 767
        if self.bad == "zero":
            vectors[0] = (0.0,) * 768
        count = sum(map(len, texts))
        return EmbeddingResult(tuple(vectors), "text-embedding-3-small", 768, count, count)


@pytest.fixture
def indexing_env():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    owner, other = uuid4(), uuid4()
    tokenizer = CharTokenizer()
    provider = FakeEmbeddings()
    chunker = DeterministicChunker(tokenizer, ChunkingConfig(overlap_tokens=0))
    clock_value = [datetime.now(timezone.utc)]
    service = VersionedIndexService(
        sessions, chunker, provider, tokenizer=tokenizer,
        embedding_model="text-embedding-3-small", clock=lambda: clock_value[0],
    )
    with sessions.begin() as session:
        assistant = Assistant(owner_id=owner, **payload())
        session.add(assistant)
        session.flush()
        assistant_id = assistant.id
        repository = KnowledgeRepository(session)
        item = repository.reserve(owner, assistant_id, filename="faq.pdf", file_format="pdf",
            size_bytes=100, content_sha256="a" * 64,
            lease_expires_at=clock_value[0] + timedelta(minutes=5))
        repository.start_processing(owner, assistant_id, item.id, item.operation_id)
        repository.complete_extraction(owner, assistant_id, item.id, item.operation_id,
            extracted_text="x" * 6000, extraction_version="extract-v1")
        file_id = item.id
    yield sessions, service, provider, owner, other, assistant_id, file_id, clock_value
    engine.dispose()


def test_version_is_invisible_until_all_batches_complete_and_reuses_ready(indexing_env):
    sessions, service, provider, owner, _, assistant_id, _, _ = indexing_env
    started = service.start(owner, assistant_id, uuid4())
    assert started.state == "building" and started.total_chunks == 10
    with sessions() as session:
        assistant = session.get(Assistant, assistant_id)
        assert assistant.active_knowledge_index_id is None
    asyncio = pytest.importorskip("asyncio")
    first = asyncio.run(service.advance(owner, assistant_id, started.index_id))
    assert first.state == "building" and first.completed_chunks == 8
    with sessions() as session:
        assert session.get(Assistant, assistant_id).active_knowledge_index_id is None
    final = asyncio.run(service.advance(owner, assistant_id, started.index_id))
    assert final.state == "ready" and final.completed_chunks == 10
    with sessions() as session:
        assistant = session.get(Assistant, assistant_id)
        chunks = session.scalars(select(KnowledgeChunk)).all()
        assert assistant.active_knowledge_index_id == started.index_id
        assert len(chunks) == 10
    reused = service.start(owner, assistant_id, uuid4())
    assert reused.index_id == started.index_id and len(provider.calls) == 2


def test_status_derives_readiness_and_detects_changed_sources(indexing_env):
    sessions, service, _, owner, other, assistant_id, _, _ = indexing_env
    before = service.status(owner, assistant_id)
    assert before.state == "needs_preparation"
    assert before.eligible_files == 1
    with pytest.raises(IndexingFailure, match="assistant_not_found"):
        service.status(other, assistant_id)

    started = service.start(owner, assistant_id, uuid4())
    asyncio = pytest.importorskip("asyncio")
    asyncio.run(service.advance(owner, assistant_id, started.index_id))
    asyncio.run(service.advance(owner, assistant_id, started.index_id))
    ready = service.status(owner, assistant_id)
    assert ready.state == "ready" and ready.operation_id == started.index_id
    assert ready.completed_chunks == ready.total_chunks == 10

    with sessions.begin() as session:
        source = session.scalar(select(KnowledgeFileText))
        source.extracted_text += " changed"
    stale = service.status(owner, assistant_id)
    assert stale.state == "needs_preparation"
    assert stale.error_code == "source_changed"


def test_batch_idempotency_key_does_not_repeat_completed_provider_work(indexing_env):
    _, service, provider, owner, _, assistant_id, _, _ = indexing_env
    started = service.start(owner, assistant_id, uuid4())
    key = uuid4()
    asyncio = pytest.importorskip("asyncio")
    first = asyncio.run(service.advance(owner, assistant_id, started.index_id,
                                        idempotency_key=key))
    calls = len(provider.calls)
    repeated = asyncio.run(service.advance(owner, assistant_id, started.index_id,
                                           idempotency_key=key))
    assert first.completed_chunks == repeated.completed_chunks == 8
    assert len(provider.calls) == calls == 1


def test_owner_scope_and_request_idempotency(indexing_env):
    _, service, provider, owner, other, assistant_id, _, _ = indexing_env
    key = uuid4()
    created = service.start(owner, assistant_id, key)
    assert service.start(owner, assistant_id, key).index_id == created.index_id
    with pytest.raises(IndexingFailure, match="assistant_not_found"):
        service.start(other, assistant_id, uuid4())
    with pytest.raises(IndexingFailure, match="index_not_found"):
        pytest.importorskip("asyncio").run(service.advance(other, assistant_id, created.index_id))
    assert provider.calls == []


def test_concurrent_worker_refused_while_batch_lease_is_live(indexing_env):
    sessions, service, _, owner, _, assistant_id, _, _ = indexing_env
    created = service.start(owner, assistant_id, uuid4())
    with sessions.begin() as session:
        batch = session.scalar(select(KnowledgeIndexBatch).where(KnowledgeIndexBatch.index_id == created.index_id))
        batch.state = "inflight"
        batch.lease_expires_at = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    with pytest.raises(IndexingFailure, match="preparation_busy"):
        pytest.importorskip("asyncio").run(service.advance(owner, assistant_id, created.index_id))


def test_expired_index_resumes_only_when_pending_batch_has_no_provider_attempt(indexing_env):
    sessions, service, provider, owner, _, assistant_id, _, clock = indexing_env
    created = service.start(owner, assistant_id, uuid4())
    clock[0] += timedelta(minutes=2)
    key = uuid4()

    resumed = pytest.importorskip("asyncio").run(service.advance(
        owner, assistant_id, created.index_id, idempotency_key=key))

    assert resumed.state == "building"
    assert resumed.completed_chunks == 8
    assert len(provider.calls) == 1
    with sessions() as session:
        index = session.get(KnowledgeIndex, created.index_id)
        batch = session.scalar(select(KnowledgeIndexBatch).where(
            KnowledgeIndexBatch.index_id == created.index_id))
        assert indexing_module._as_utc(index.lease_expires_at) > clock[0]
        assert batch.state == "completed" and batch.attempts == 1


def test_expired_index_does_not_resume_batch_with_prior_provider_attempt(indexing_env):
    sessions, service, provider, owner, _, assistant_id, _, clock = indexing_env
    created = service.start(owner, assistant_id, uuid4())
    clock[0] += timedelta(minutes=2)
    with sessions.begin() as session:
        batch = session.scalar(select(KnowledgeIndexBatch).where(
            KnowledgeIndexBatch.index_id == created.index_id))
        batch.attempts = 1

    with pytest.raises(IndexingFailure, match="index_lease_expired"):
        pytest.importorskip("asyncio").run(service.advance(owner, assistant_id, created.index_id))
    assert provider.calls == []


def test_expired_attempt_requires_operator_retry_approval(indexing_env):
    sessions, service, _, owner, _, assistant_id, _, clock = indexing_env
    created = service.start(owner, assistant_id, uuid4())
    with sessions.begin() as session:
        batch = session.scalar(select(KnowledgeIndexBatch).where(KnowledgeIndexBatch.index_id == created.index_id))
        batch.state = "inflight"
        batch.lease_expires_at = clock[0] - timedelta(seconds=1)
    uncertain = service.recover_expired_batch(owner, assistant_id, created.index_id, 0)
    assert uncertain.state == "failed" and uncertain.error_code == "provider_attempt_uncertain"
    status = service.status(owner, assistant_id)
    assert status.state == "failed" and status.error_code == "provider_attempt_uncertain"
    with pytest.raises(IndexingFailure, match="provider_attempt_uncertain"):
        service.start(owner, assistant_id, uuid4())
    with sessions() as session:
        batch = session.scalar(select(KnowledgeIndexBatch).where(KnowledgeIndexBatch.index_id == created.index_id))
        assert batch.state == "uncertain"


@pytest.mark.parametrize("bad", ["dimension", "nan", "zero"])
def test_invalid_vectors_fail_index_without_activation(indexing_env, bad):
    sessions, service, _, owner, _, assistant_id, _, _ = indexing_env
    provider = FakeEmbeddings(bad=bad)
    service.provider = provider
    created = service.start(owner, assistant_id, uuid4())
    with pytest.raises(IndexingFailure, match="embedding_invalid_output"):
        pytest.importorskip("asyncio").run(service.advance(owner, assistant_id, created.index_id))
    with sessions() as session:
        index = session.get(KnowledgeIndex, created.index_id)
        assistant = session.get(Assistant, assistant_id)
        assert index.state == "failed" and assistant.active_knowledge_index_id is None
        assert session.scalar(select(KnowledgeChunk.id)) is None


def test_provider_failure_is_distinct_from_source_processing_failure(indexing_env):
    sessions, service, _, owner, _, assistant_id, _, _ = indexing_env
    service.provider = FakeEmbeddings(failure=EmbeddingFailure("embedding_quota_or_rate_limited"))
    created = service.start(owner, assistant_id, uuid4())
    with pytest.raises(IndexingFailure, match="embedding_provider_failure"):
        pytest.importorskip("asyncio").run(service.advance(owner, assistant_id, created.index_id))
    with sessions() as session:
        assert session.get(KnowledgeIndex, created.index_id).error_code == "embedding_provider_failure"


def test_source_removal_supersedes_incomplete_version_and_preserves_active_pointer(indexing_env):
    sessions, service, _, owner, _, assistant_id, file_id, _ = indexing_env
    created = service.start(owner, assistant_id, uuid4())
    with sessions.begin() as session:
        KnowledgeRepository(session).remove(owner, assistant_id, file_id)
    result = pytest.importorskip("asyncio").run(service.advance(owner, assistant_id, created.index_id))
    assert result.state == "superseded"
    with sessions() as session:
        assert session.get(Assistant, assistant_id).active_knowledge_index_id is None
        assert session.scalar(select(KnowledgeChunk.id)) is None


def test_newly_extracted_source_supersedes_old_manifest_before_provider_call(indexing_env):
    sessions, service, provider, owner, _, assistant_id, _, _ = indexing_env
    created = service.start(owner, assistant_id, uuid4())
    with sessions.begin() as session:
        repository = KnowledgeRepository(session)
        item = repository.reserve(owner, assistant_id, filename="new.pdf", file_format="pdf",
            size_bytes=100, content_sha256="b" * 64,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        repository.start_processing(owner, assistant_id, item.id, item.operation_id)
        repository.complete_extraction(owner, assistant_id, item.id, item.operation_id,
            extracted_text="new knowledge", extraction_version="extract-v1")
    result = pytest.importorskip("asyncio").run(service.advance(owner, assistant_id, created.index_id))
    assert result.state == "superseded"
    assert provider.calls == []


def test_removing_source_clears_previously_active_index(indexing_env):
    sessions, service, _, owner, _, assistant_id, file_id, _ = indexing_env
    started = service.start(owner, assistant_id, uuid4())
    asyncio = pytest.importorskip("asyncio")
    asyncio.run(service.advance(owner, assistant_id, started.index_id))
    asyncio.run(service.advance(owner, assistant_id, started.index_id))
    with sessions.begin() as session:
        assert session.get(Assistant, assistant_id).active_knowledge_index_id == started.index_id
        KnowledgeRepository(session).remove(owner, assistant_id, file_id)
    with sessions() as session:
        assert session.get(Assistant, assistant_id).active_knowledge_index_id is None


def test_embedding_batches_respect_item_and_token_limits():
    tokenizer = CharTokenizer()
    owner, assistant = uuid4(), uuid4()
    from assistant_builder.chunking import SourceText, DeterministicChunker
    chunker = DeterministicChunker(tokenizer, ChunkingConfig(overlap_tokens=0))
    chunks = chunker.chunk([SourceText(owner, assistant, uuid4(), "v1", "a" * 6000)])
    batches = split_embedding_batches(chunks, tokenizer)
    assert [len(batch) for batch in batches] == [8, 2]
    assert all(sum(len(tokenizer.encode(item.text)) for item in batch) <= 4800 for batch in batches)
    with pytest.raises(IndexingFailure, match="index_input_limit"):
        split_embedding_batches(chunks, tokenizer, max_tokens=500)


def test_second_batch_failure_keeps_partial_rows_invisible(indexing_env):
    sessions, service, _, owner, _, assistant_id, _, _ = indexing_env
    provider = FakeEmbeddings(fail_on_call=2)
    service.provider = provider
    created = service.start(owner, assistant_id, uuid4())
    asyncio = pytest.importorskip("asyncio")
    first = asyncio.run(service.advance(owner, assistant_id, created.index_id))
    assert first.state == "building" and first.completed_chunks == 8
    with pytest.raises(IndexingFailure, match="embedding_provider_failure"):
        asyncio.run(service.advance(owner, assistant_id, created.index_id))
    with sessions() as session:
        index = session.get(KnowledgeIndex, created.index_id)
        assert index.state == "failed" and index.completed_chunks == 8
        assert session.scalar(select(KnowledgeChunk.id).limit(1)) is not None
        assert session.get(Assistant, assistant_id).active_knowledge_index_id is None


def test_empty_corpus_rejected_and_start_transaction_rolls_back(indexing_env):
    sessions, service, _, owner, _, assistant_id, file_id, _ = indexing_env
    service.chunker = DeterministicChunker(CharTokenizer(), ChunkingConfig(overlap_tokens=0))
    with sessions.begin() as session:
        file = session.get(KnowledgeFile, file_id)
        file.removed_at = datetime.now(timezone.utc)
        file.slot_number = None
    with pytest.raises(IndexingFailure, match="no_knowledge"):
        service.start(owner, assistant_id, uuid4())
    with sessions() as session:
        assert session.scalar(select(KnowledgeIndex.id)) is None


def test_cost_guard_rolls_back_index_and_batch_reservations(indexing_env, monkeypatch):
    sessions, service, provider, owner, _, assistant_id, _, _ = indexing_env
    monkeypatch.setattr(indexing_module, "MAX_INDEX_COST_MICRO_USD", 0)
    with pytest.raises(IndexingFailure, match="index_cost_limit"):
        service.start(owner, assistant_id, uuid4())
    with sessions() as session:
        assert session.scalar(select(KnowledgeIndex.id)) is None
        assert session.scalar(select(KnowledgeIndexBatch.id)) is None
    assert provider.calls == []
