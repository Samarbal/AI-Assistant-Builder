"""Opt-in loopback PostgreSQL retrieval and RLS integration test; never uses .env."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from assistant_builder.chunking import ChunkingConfig, DeterministicChunker
from assistant_builder.db import set_owner_identity
from assistant_builder.embeddings import EmbeddingResult
from assistant_builder.indexing import VersionedIndexService
from assistant_builder.knowledge_repository import KnowledgeRepository
from assistant_builder.models import Assistant
from assistant_builder.retrieval import PgVectorRetriever, RetrievalFailure
from .test_phase1_contracts import payload
from .test_postgresql_phase1 import postgres


class LocalTestTokenizer:
    fingerprint = "retrieval-integration-char-v1"

    def encode(self, value):
        return [ord(char) for char in value]

    def offsets(self, tokens, value):
        return list(range(len(value) + 1))


class LocalTestEmbeddings:
    async def embed(self, texts):
        vector = (1.0,) + (0.0,) * 767
        return EmbeddingResult(tuple(vector for _ in texts), "text-embedding-3-small", 768,
                               sum(len(value) for value in texts),
                               sum(len(value) for value in texts))


def test_active_index_cosine_search_and_owner_isolation(postgres):
    admin, runtime = postgres
    engine = create_engine(runtime.url, hide_parameters=True, pool_size=2, max_overflow=0)
    factory = sessionmaker(engine, expire_on_commit=False)
    owners = [uuid4(), uuid4()]
    assistant_ids = []
    try:
        for owner in owners:
            with factory.begin() as session:
                set_owner_identity(session, owner)
                assistant = Assistant(owner_id=owner, **payload())
                session.add(assistant)
                session.flush()
                assistant_ids.append(assistant.id)

        owner, assistant_id = owners[0], assistant_ids[0]
        with factory.begin() as session:
            set_owner_identity(session, owner)
            repo = KnowledgeRepository(session)
            file = repo.reserve(owner, assistant_id, filename="synthetic.pdf", file_format="pdf",
                size_bytes=100, content_sha256="b" * 64,
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
            repo.start_processing(owner, assistant_id, file.id, file.operation_id)
            repo.complete_extraction(owner, assistant_id, file.id, file.operation_id,
                extracted_text="Synthetic policy: returns are accepted within 14 days.",
                extraction_version="retrieval-test-v1")

        tokenizer = LocalTestTokenizer()
        indexer = VersionedIndexService(factory,
            DeterministicChunker(tokenizer, ChunkingConfig(chunk_tokens=600, overlap_tokens=0)),
            LocalTestEmbeddings(), tokenizer=tokenizer,
            embedding_model="text-embedding-3-small", embedding_provider_name="openai")
        status = indexer.start(owner, assistant_id, uuid4())
        status = asyncio.run(indexer.advance(owner, assistant_id, status.index_id))
        assert status.state == "ready"

        retriever = PgVectorRetriever(factory, LocalTestEmbeddings(), minimum_similarity=0.5)
        result = asyncio.run(retriever.retrieve(owner, assistant_id, "return policy"))
        assert result.state == "matches" and result.chunks
        assert result.chunks[0].text.startswith("Synthetic policy:")
        assert result.chunks[0].similarity == pytest.approx(1.0)
        assert result.chunks[0].file_id == file.id

        with pytest.raises(RetrievalFailure, match="assistant_not_found"):
            asyncio.run(retriever.retrieve(owners[1], assistant_id, "return policy"))
        with factory.begin() as session:
            set_owner_identity(session, owners[1])
            assert session.execute(text("SELECT id FROM public.knowledge_chunks")).all() == []
    finally:
        # Cleanup is limited to UUIDs created in this test and runs only on the
        # explicitly configured dedicated loopback test database fixture.
        with admin.begin() as connection:
            for assistant_id in assistant_ids:
                connection.execute(text("UPDATE public.assistants SET active_knowledge_index_id=NULL WHERE id=:id"),
                                   {"id": assistant_id})
                connection.execute(text("DELETE FROM public.knowledge_chunks WHERE assistant_id=:id"),
                                   {"id": assistant_id})
                connection.execute(text("DELETE FROM public.knowledge_index_batches WHERE assistant_id=:id"),
                                   {"id": assistant_id})
                connection.execute(text("DELETE FROM public.knowledge_index_sources WHERE assistant_id=:id"),
                                   {"id": assistant_id})
                connection.execute(text("DELETE FROM public.knowledge_indexes WHERE assistant_id=:id"),
                                   {"id": assistant_id})
                connection.execute(text("DELETE FROM public.knowledge_file_text WHERE assistant_id=:id"),
                                   {"id": assistant_id})
                connection.execute(text("DELETE FROM public.knowledge_files WHERE assistant_id=:id"),
                                   {"id": assistant_id})
                connection.execute(text("DELETE FROM public.assistants WHERE id=:id"),
                                   {"id": assistant_id})
        engine.dispose()
