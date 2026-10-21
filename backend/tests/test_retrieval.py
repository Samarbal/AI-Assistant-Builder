from contextlib import contextmanager
from uuid import uuid4

import pytest

from assistant_builder.config import Settings
from assistant_builder.embeddings import EmbeddingFailure, EmbeddingResult
from assistant_builder.retrieval import (
    MAX_RETRIEVAL_TOP_K, PgVectorRetriever, RetrievalFailure,
)


def snapshot(*, active=None, state="ready", sources=True, pending=False,
             extracted=True, provider="openai", model="text-embedding-3-small", dimension=768):
    return {
        "active_index_id": active, "index_state": state,
        "embedding_provider": provider, "embedding_model": model,
        "vector_dimension": dimension, "has_pending_files": pending,
        "has_extracted_files": extracted, "sources_match": sources,
    }


class Mappings:
    def __init__(self, rows):
        self.rows = rows

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def mappings(self):
        return Mappings(self.rows)


class FakeSession:
    bind = type("Bind", (), {"dialect": type("Dialect", (), {"name": "sqlite"})()})()

    def __init__(self, snapshots, matches=()):
        self.snapshots = list(snapshots)
        self.matches = list(matches)
        self.searches = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        if "active_knowledge_index_id AS active_index_id" in sql:
            return Result([self.snapshots.pop(0)])
        if "c.embedding <=>" in sql:
            self.searches += 1
            assert params["top_k"] <= MAX_RETRIEVAL_TOP_K
            assert params["assistant_id"] and params["owner_id"]
            return Result(self.matches)
        raise AssertionError("Unexpected SQL")


class Factory:
    def __init__(self, session):
        self.session = session

    @contextmanager
    def begin(self):
        yield self.session


class FakeProvider:
    model = "text-embedding-3-small"
    dimensions = 768

    def __init__(self, failure=None, model=None, vector=None):
        self.calls = []
        self.failure = failure
        self.model = model or self.model
        self.vector = vector or ((1.0,) + (0.0,) * 767)

    async def embed(self, texts):
        self.calls.append(texts)
        if self.failure:
            raise self.failure
        return EmbeddingResult((self.vector,), self.model, self.dimensions, 2, 2)


def make_match(**changes):
    values = {
        "file_id": uuid4(), "chunk_id": uuid4(), "filename": "guide.docx",
        "chunk_text": "Synthetic returns are accepted within 14 days.",
        "similarity": 0.91, "start_offset": 0, "end_offset": 47,
        "extraction_version": "extract-v1",
    }
    values.update(changes)
    return values


def make_retriever(session, provider, *, threshold=0.7):
    return PgVectorRetriever(Factory(session), provider, minimum_similarity=threshold)


@pytest.mark.parametrize("top_k", [0, 6, True, "5"])
def test_rejects_unbounded_or_invalid_top_k_without_provider_call(top_k):
    provider = FakeProvider()
    retriever = make_retriever(FakeSession([]), provider)
    with pytest.raises(RetrievalFailure, match="retrieval_invalid_request"):
        import asyncio
        asyncio.run(retriever.retrieve(uuid4(), uuid4(), "question", top_k=top_k))
    assert provider.calls == []


def test_no_active_index_returns_readiness_without_embedding():
    provider = FakeProvider()
    retriever = make_retriever(FakeSession([snapshot(extracted=True)]), provider)
    import asyncio
    result = asyncio.run(retriever.retrieve(uuid4(), uuid4(), "question"))
    assert result.state == "needs_preparation" and result.chunks == ()
    assert provider.calls == []


def test_no_knowledge_returns_empty_state_without_embedding():
    provider = FakeProvider()
    retriever = make_retriever(FakeSession([snapshot(extracted=False)]), provider)
    import asyncio
    result = asyncio.run(retriever.retrieve(uuid4(), uuid4(), "question"))
    assert result.state == "no_knowledge"
    assert provider.calls == []


@pytest.mark.parametrize("state", ["building", "failed", "superseded"])
def test_non_ready_index_fails_closed_without_embedding(state):
    provider = FakeProvider()
    retriever = make_retriever(FakeSession([snapshot(active=uuid4(), state=state)]), provider)
    with pytest.raises(RetrievalFailure, match="knowledge_not_ready"):
        import asyncio
        asyncio.run(retriever.retrieve(uuid4(), uuid4(), "question"))
    assert provider.calls == []


def test_pending_file_blocks_active_index():
    provider = FakeProvider()
    retriever = make_retriever(FakeSession([snapshot(active=uuid4(), pending=True)]), provider)
    with pytest.raises(RetrievalFailure, match="knowledge_not_ready"):
        import asyncio
        asyncio.run(retriever.retrieve(uuid4(), uuid4(), "question"))
    assert provider.calls == []


def test_retrieves_owner_scoped_results_from_active_index_only():
    owner, assistant, index = uuid4(), uuid4(), uuid4()
    session = FakeSession([snapshot(active=index), snapshot(active=index)], [make_match()])
    provider = FakeProvider()
    retriever = make_retriever(session, provider)
    import asyncio
    result = asyncio.run(retriever.retrieve(owner, assistant, "How long are returns?", top_k=3))
    assert result.state == "matches" and len(result.chunks) == 1
    match = result.chunks[0]
    assert match.filename == "guide.docx" and "14 days" in match.text
    assert match.similarity == pytest.approx(0.91)
    assert match.file_id and match.chunk_id and match.extraction_version == "extract-v1"
    assert provider.calls == [("How long are returns?",)]
    assert session.searches == 1


def test_concurrent_index_change_discards_embedded_query():
    index = uuid4()
    provider = FakeProvider()
    session = FakeSession([snapshot(active=index), snapshot(active=uuid4())])
    retriever = make_retriever(session, provider)
    with pytest.raises(RetrievalFailure, match="knowledge_not_ready"):
        import asyncio
        asyncio.run(retriever.retrieve(uuid4(), uuid4(), "question"))
    assert provider.calls and session.searches == 0


def test_stale_or_incomplete_source_manifest_is_not_searched():
    provider = FakeProvider()
    retriever = make_retriever(FakeSession([snapshot(active=uuid4(), sources=False)]), provider)
    with pytest.raises(RetrievalFailure, match="knowledge_not_ready"):
        import asyncio
        asyncio.run(retriever.retrieve(uuid4(), uuid4(), "question"))
    assert provider.calls == []


def test_embedding_failure_is_not_reported_as_empty_knowledge():
    provider = FakeProvider(failure=EmbeddingFailure("embedding_timeout"))
    index = uuid4()
    retriever = make_retriever(FakeSession([snapshot(active=index)]), provider)
    with pytest.raises(RetrievalFailure, match="embedding_unavailable"):
        import asyncio
        asyncio.run(retriever.retrieve(uuid4(), uuid4(), "question"))


def test_embedding_space_mismatch_fails_before_search():
    provider = FakeProvider(model="different-model")
    index = uuid4()
    session = FakeSession([snapshot(active=index)])
    retriever = make_retriever(session, provider)
    with pytest.raises(RetrievalFailure, match="embedding_space_mismatch"):
        import asyncio
        asyncio.run(retriever.retrieve(uuid4(), uuid4(), "question"))
    assert session.searches == 0


def test_empty_matches_are_explicit_no_relevant_chunks():
    index = uuid4()
    session = FakeSession([snapshot(active=index), snapshot(active=index)])
    provider = FakeProvider()
    retriever = make_retriever(session, provider)
    import asyncio
    result = asyncio.run(retriever.retrieve(uuid4(), uuid4(), "unknown question"))
    assert result.state == "no_relevant_chunks" and result.chunks == ()


def test_similarity_threshold_is_required_and_bounded():
    with pytest.raises(RetrievalFailure, match="retrieval_configuration"):
        PgVectorRetriever(Factory(FakeSession([])), FakeProvider(), minimum_similarity=float("nan"))


def test_similarity_threshold_is_explicitly_configurable_without_hidden_default():
    assert Settings(_env_file=None).retrieval_min_similarity is None
    assert Settings(_env_file=None, retrieval_min_similarity=0.534433).retrieval_min_similarity == pytest.approx(0.534433)


def test_sql_contract_scopes_all_ids_and_uses_exact_cosine_top_k():
    from assistant_builder.retrieval import _SEARCH_SQL, _SNAPSHOT_SQL

    sql = str(_SEARCH_SQL)
    assert "a.active_knowledge_index_id=:index_id" in sql
    assert "i.state='ready'" in sql
    assert "c.owner_id=i.owner_id" in sql and "c.assistant_id=i.assistant_id" in sql
    assert "f.removed_at IS NULL" in sql
    assert "c.embedding <=> CAST(:query_vector AS public.vector(768))" in sql
    assert "LIMIT :top_k" in sql


def test_source_hash_is_compared_with_extracted_chunk_hash_not_uploaded_binary_hash():
    from assistant_builder.retrieval import _SEARCH_SQL, _SNAPSHOT_SQL

    snapshot_sql = str(_SNAPSHOT_SQL)
    search_sql = str(_SEARCH_SQL)
    # source_sha256 identifies extracted text (also copied to each chunk), whereas
    # content_sha256 identifies the uploaded PDF/DOCX bytes. Those hashes differ.
    assert "c.source_sha256=s.source_sha256" in snapshot_sql
    assert "c.source_sha256=s.source_sha256" in search_sql
    assert "f.content_sha256=s.source_sha256" not in snapshot_sql
    assert "f.content_sha256=s.source_sha256" not in search_sql
