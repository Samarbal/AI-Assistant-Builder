"""Opt-in real PostgreSQL tests for Phase 4 publication and budget boundaries.

Use only a disposable loopback database; the migration fixture is shared with
the Phase 1 PostgreSQL suite and applies Alembic head before tests execute.
"""
from concurrent.futures import ThreadPoolExecutor
import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy import event

from assistant_builder.auth import OwnerContext
from assistant_builder.db import set_owner_identity, validate_public_runtime_role
from assistant_builder.models import (Assistant, KnowledgeChunk, KnowledgeFile,
    KnowledgeFileText, KnowledgeIndex, KnowledgeIndexSource, PublishedSource)
from assistant_builder.publication import PublicationFailure, PublicationService
from assistant_builder.public_chat import PublicChatService, PublicRequestGuard, PublicChatFailure
from assistant_builder.conversation_history import ConversationHistoryNotFound, ConversationHistoryService
from assistant_builder.generation import Answer, Citation
from .test_postgresql_phase1 import postgres
from .test_phase1_contracts import payload


@pytest.fixture
def p4_db(postgres):
    return postgres


def _public_role_factory(admin):
    """Test RLS/grants as assistant_public_runtime; disposable DB only."""
    public_engine = create_engine(admin.url, hide_parameters=True)
    @event.listens_for(public_engine, "connect")
    def assume_public_role(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("SET ROLE assistant_public_runtime")
        cursor.close()
        # SQLAlchemy rolls back a newly opened DBAPI connection on checkout;
        # commit SET ROLE so every test transaction really runs as this role.
        dbapi_connection.commit()
    validate_public_runtime_role(public_engine)
    return public_engine, sessionmaker(public_engine, expire_on_commit=False)


def test_public_runtime_fallback_chat_is_snapshot_scoped_and_idempotent(p4_db):
    admin, owner_runtime = p4_db
    owner = uuid4()
    assistant = _assistant(sessionmaker(owner_runtime, expire_on_commit=False), owner)
    factory = sessionmaker(owner_runtime, expire_on_commit=False)
    with factory.begin() as session:
        set_owner_identity(session, owner)
        current = PublicationService(session, embedding_provider="openai",
            embedding_model="text-embedding-3-small").status(owner, assistant)
        publication, snapshot, _ = PublicationService(session, embedding_provider="openai",
            embedding_model="text-embedding-3-small").publish(owner, assistant,
            expected_fingerprint=current["draft_fingerprint"], expected_version=None,
            idempotency_key="public-fallback-publish")
        public_id, snapshot_id = publication.public_id, snapshot.id

    public_engine, public_factory = _public_role_factory(admin)
    class NeverEmbeddings:
        async def embed(self, texts):
            raise AssertionError("fallback-only publication must not embed")
    class NeverGenerator:
        async def generate(self, *args):
            raise AssertionError("fallback-only publication must not generate")
    service = PublicChatService(public_factory, NeverEmbeddings(), NeverGenerator(), PublicRequestGuard())
    assert service.public_details(public_id)["version"] == 1
    conversation = service.create_conversation(public_id)
    assert timedelta(hours=23, minutes=59) < conversation["expires_at"] - datetime.now(timezone.utc) <= timedelta(hours=24)
    with admin.connect() as conn:
        stored_digest = conn.scalar(text("SELECT token_sha256 FROM public.visitor_conversations WHERE id=:id"),
                                    {"id": conversation["conversation_id"]})
    assert stored_digest == sha256(conversation["conversation_token"].encode()).hexdigest()
    import asyncio
    request_id = uuid4()
    result = asyncio.run(service.message(public_id, conversation["conversation_id"],
        conversation["conversation_token"], "synthetic question", request_id))
    assert result["answer"] == payload()["fallback_message"]
    assert result["outcome"] == "fallback"
    replay = asyncio.run(service.message(public_id, conversation["conversation_id"],
        conversation["conversation_token"], "synthetic question", request_id))
    assert replay["message_id"] == result["message_id"]
    with pytest.raises(PublicChatFailure, match="request_conflict"):
        asyncio.run(service.message(public_id, conversation["conversation_id"],
            conversation["conversation_token"], "different", request_id))
    with public_factory.begin() as session:
        with pytest.raises(DBAPIError):
            session.execute(text("SELECT * FROM public.assistants")).all()
    with admin.connect() as conn:
        assert conn.scalar(text("SELECT state FROM public.visitor_turns WHERE id=:id"),
                           {"id": result["message_id"]}) == "fallback"
        assert conn.scalar(text("SELECT count(*) FROM public.visitor_turns WHERE owner_id=:owner"),
                           {"owner": owner}) == 1


def test_owner_conversation_history_paginates_and_hides_cross_owner_rows(p4_db):
    admin, runtime = p4_db
    owner_factory = sessionmaker(runtime, expire_on_commit=False)
    owner_a, owner_b = uuid4(), uuid4()
    assistant_a = _assistant(owner_factory, owner_a)
    assistant_b = _assistant(owner_factory, owner_b)
    publications = []
    for owner, assistant, key in ((owner_a, assistant_a, "history-pub-a"),
                                  (owner_b, assistant_b, "history-pub-b")):
        with owner_factory.begin() as session:
            set_owner_identity(session, owner)
            pub, snapshot, _ = PublicationService(session, embedding_provider="openai",
                embedding_model="text-embedding-3-small").publish(
                    owner, assistant, expected_fingerprint=PublicationService(
                        session, embedding_provider="openai", embedding_model="text-embedding-3-small"
                    ).status(owner, assistant)["draft_fingerprint"], expected_version=None,
                    idempotency_key=key)
            publications.append((pub.public_id, snapshot.id))

    public_engine, public_factory = _public_role_factory(admin)
    class NeverEmbeddings:
        model, dimension = "openai/test", 768
        async def embed(self, texts):
            raise AssertionError("fallback-only history fixture must not embed")
    class NeverGenerator:
        async def generate(self, *args):
            raise AssertionError("fallback-only history fixture must not generate")
    public_service = PublicChatService(public_factory, NeverEmbeddings(), NeverGenerator(), PublicRequestGuard())
    try:
        conversations_a = [public_service.create_conversation(publications[0][0]) for _ in range(3)]
        conversation_b = public_service.create_conversation(publications[1][0])
        request_id = uuid4()
        first = asyncio.run(public_service.message(publications[0][0], conversations_a[0]["conversation_id"],
            conversations_a[0]["conversation_token"], "synthetic history question", request_id))
        replay = asyncio.run(public_service.message(publications[0][0], conversations_a[0]["conversation_id"],
            conversations_a[0]["conversation_token"], "synthetic history question", request_id))
        assert replay["message_id"] == first["message_id"]
        second = asyncio.run(public_service.message(publications[0][0], conversations_a[0]["conversation_id"],
            conversations_a[0]["conversation_token"], "second synthetic turn", uuid4()))
        assert second["message_id"] != first["message_id"]

        with owner_factory.begin() as session:
            set_owner_identity(session, owner_a)
            session.get(Assistant, assistant_a).fallback_message = "Updated synthetic fallback"
            publisher = PublicationService(session, embedding_provider="openai",
                embedding_model="text-embedding-3-small")
            fingerprint = publisher.status(owner_a, assistant_a)["draft_fingerprint"]
            _, snapshot_v2, _ = publisher.publish(owner_a, assistant_a,
                expected_fingerprint=fingerprint, expected_version=1, idempotency_key="history-pub-a-v2")
            assert snapshot_v2.version == 2
        conversation_v2 = public_service.create_conversation(publications[0][0])
        asyncio.run(public_service.message(publications[0][0], conversation_v2["conversation_id"],
            conversation_v2["conversation_token"], "version two synthetic turn", uuid4()))

        with owner_factory.begin() as session:
            set_owner_identity(session, owner_a)
            history = ConversationHistoryService(session)
            page1 = history.list_conversations(owner_a, assistant_a, limit=1)
            page2 = history.list_conversations(owner_a, assistant_a, limit=1, cursor=page1["next_cursor"])
            page3 = history.list_conversations(owner_a, assistant_a, limit=1, cursor=page2["next_cursor"])
            page4 = history.list_conversations(owner_a, assistant_a, limit=1, cursor=page3["next_cursor"])
            ids = [page1["items"][0]["conversation_id"], page2["items"][0]["conversation_id"],
                   page3["items"][0]["conversation_id"], page4["items"][0]["conversation_id"]]
            assert len(set(ids)) == 4
            assert page4["next_cursor"] is None
            summary_by_id = {page["items"][0]["conversation_id"]: page["items"][0]
                             for page in (page1, page2, page3, page4)}
            assert summary_by_id[conversations_a[0]["conversation_id"]]["latest_status"] == "fallback"
            assert summary_by_id[conversations_a[0]["conversation_id"]]["latest_published_version"] == 1
            assert summary_by_id[conversation_v2["conversation_id"]]["latest_published_version"] == 2

            detail1 = history.get_conversation(owner_a, assistant_a, conversations_a[0]["conversation_id"], limit=1)
            assert len(detail1["turns"]) == 1 and detail1["next_cursor"]
            detail2 = history.get_conversation(owner_a, assistant_a, conversations_a[0]["conversation_id"],
                                               limit=1, cursor=detail1["next_cursor"])
            assert len(detail2["turns"]) == 1 and detail2["next_cursor"] is None
            turn = detail1["turns"][0]
            assert turn["user_message"] == "synthetic history question"
            assert turn["assistant_message"] == "I cannot find that answer in the provided information."
            assert (turn["status"], turn["outcome"], turn["published_version"]) == ("fallback", "fallback", 1)
            next_turn = detail2["turns"][0]
            assert next_turn["user_message"] == "second synthetic turn" and next_turn["published_version"] == 1
            newer = history.get_conversation(owner_a, assistant_a, conversation_v2["conversation_id"], limit=10)
            assert newer["turns"][0]["published_version"] == 2
            assert newer["turns"][0]["assistant_message"] == "Updated synthetic fallback"
            with pytest.raises(ConversationHistoryNotFound):
                history.get_conversation(owner_a, assistant_a, conversation_b["conversation_id"], limit=10)
            with pytest.raises(ConversationHistoryNotFound):
                history.get_conversation(owner_a, assistant_b, conversations_a[0]["conversation_id"], limit=10)
        with admin.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM public.visitor_turns WHERE conversation_id=:id"),
                               {"id": conversations_a[0]["conversation_id"]}) == 2
    finally:
        public_engine.dispose()
    public_engine.dispose()


def test_public_retrieval_uses_published_index_and_hides_citations(p4_db):
    import asyncio
    from types import SimpleNamespace

    admin, runtime = p4_db
    owner, assistant = uuid4(), None
    owner_factory = sessionmaker(runtime, expire_on_commit=False)
    assistant = _assistant(owner_factory, owner)
    file_id, index_id, chunk_id = uuid4(), uuid4(), uuid4()
    extracted = "Synthetic published evidence says the demo office opens at nine."
    source_hash = sha256(extracted.encode()).hexdigest()
    content_hash = sha256(b"synthetic test file").hexdigest()
    manifest = sha256(json.dumps([{
        "file_id": str(file_id), "content_sha256": content_hash,
        "extraction_version": "extract-v1", "text_sha256": source_hash,
    }], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    now = datetime.now(timezone.utc)
    seed_factory = sessionmaker(admin, expire_on_commit=False)
    with seed_factory.begin() as session:
        session.add(KnowledgeFile(id=file_id, owner_id=owner, assistant_id=assistant,
            slot_number=1, original_filename="private-fixture-name.docx", file_format="docx",
            size_bytes=128, content_sha256=content_hash,
            object_key=f"owners/{owner}/assistants/{assistant}/files/{file_id}/original.docx",
            processing_state="extracted", operation_id=uuid4(),
            lease_expires_at=now + timedelta(minutes=1), cleanup_state="not_needed"))
        session.flush()
        session.add(KnowledgeFileText(file_id=file_id, assistant_id=assistant,
            owner_id=owner, extracted_text=extracted, extraction_version="extract-v1"))
        session.add(KnowledgeIndex(id=index_id, owner_id=owner, assistant_id=assistant,
            version=1, idempotency_key=uuid4(), manifest_sha256=manifest,
            embedding_provider="openai", embedding_model="text-embedding-3-small",
            vector_dimension=768, tokenizer_version="cl100k_base",
            chunker_version="fixed-600-100-v1", state="ready", operation_id=uuid4(),
            lease_expires_at=now + timedelta(minutes=1), total_chunks=1,
            completed_chunks=1, ready_at=now))
        session.flush()
        session.add(KnowledgeIndexSource(index_id=index_id, file_id=file_id,
            assistant_id=assistant, owner_id=owner, extraction_version="extract-v1",
            source_sha256=source_hash))
        session.flush()
        session.add(KnowledgeChunk(id=chunk_id, index_id=index_id, owner_id=owner,
            assistant_id=assistant, file_id=file_id, ordinal=0,
            extraction_version="extract-v1", chunker_version="fixed-600-100-v1",
            source_sha256=source_hash, start_offset=0, end_offset=len(extracted),
            token_count=12, text_sha256=source_hash, chunk_text=extracted,
            embedding=tuple([1.0] + [0.0] * 767)))
        session.get(Assistant, assistant).active_knowledge_index_id = index_id

    with owner_factory.begin() as session:
        set_owner_identity(session, owner)
        current = PublicationService(session, embedding_provider="openai",
            embedding_model="text-embedding-3-small", minimum_similarity=0.3).status(owner, assistant)
        publication, snapshot, _ = PublicationService(session, embedding_provider="openai",
            embedding_model="text-embedding-3-small", minimum_similarity=0.3).publish(
                owner, assistant, expected_fingerprint=current["draft_fingerprint"],
                expected_version=None, idempotency_key="public-indexed-chat")

    snapshot_id = snapshot.id
    public_engine, public_factory = _public_role_factory(admin)
    class FakeEmbeddings:
        model = "text-embedding-3-small"
        dimension = 768
        async def embed(self, texts):
            return SimpleNamespace(model=self.model, dimensions=768,
                vectors=(tuple([1.0] + [0.0] * 767),))
    class FakeGenerator:
        async def generate(self, behavior, question, evidence):
            return Answer("The office opens at nine.", "grounded", (
                Citation(file_id, chunk_id, "Published knowledge", extracted[:40]),))
    service = PublicChatService(public_factory, FakeEmbeddings(), FakeGenerator(), PublicRequestGuard())
    try:
        conversation = service.create_conversation(publication.public_id)
        result = asyncio.run(service.message(publication.public_id, conversation["conversation_id"],
            conversation["conversation_token"], "When does the office open?", uuid4()))
        assert result["outcome"] == "grounded"
        assert result["answer"] == "The office opens at nine."
        assert "citations" not in result
        assert "private-fixture-name.docx" not in repr(result)
        with public_factory.begin() as session:
            session.execute(text("SELECT set_config('app.public_id',:v,true)"),
                            {"v": str(publication.public_id)})
            session.execute(text("SELECT set_config('app.snapshot_id',:v,true)"),
                            {"v": str(snapshot_id)})
            assert session.scalar(text("SELECT count(*) FROM public.knowledge_chunks")) == 1
            # Missing snapshot identity fails closed even though the role can read
            # the published index's chunks with the correct context.
            session.execute(text("SELECT set_config('app.snapshot_id','',true)"))
            assert session.scalar(text("SELECT count(*) FROM public.knowledge_chunks")) == 0

        # A publish that wins while generation is in flight must invalidate the
        # answer and persist a terminal version_rejected row without answer text.
        class SwitchingGenerator:
            async def generate(self, behavior, question, evidence):
                with owner_factory.begin() as session:
                    set_owner_identity(session, owner)
                    session.get(Assistant, assistant).fallback_message = "Changed published fallback."
                with owner_factory.begin() as session:
                    set_owner_identity(session, owner)
                    workflow = PublicationService(session, embedding_provider="openai",
                        embedding_model="text-embedding-3-small", minimum_similarity=0.3)
                    state = workflow.status(owner, assistant)
                    workflow.publish(owner, assistant, expected_fingerprint=state["draft_fingerprint"],
                        expected_version=1, idempotency_key="publish-during-public-answer")
                return Answer("The office opens at nine.", "grounded", (
                    Citation(file_id, chunk_id, "Published knowledge", extracted[:40]),))
        service.generator = SwitchingGenerator()
        next_conversation = service.create_conversation(publication.public_id)
        with pytest.raises(PublicChatFailure, match="published_version_changed"):
            asyncio.run(service.message(publication.public_id, next_conversation["conversation_id"],
                next_conversation["conversation_token"], "When does the office open?", uuid4()))
        with admin.connect() as conn:
            rejected = conn.execute(text("SELECT state,answer_text FROM public.visitor_turns "
                "WHERE conversation_id=:conversation ORDER BY created_at DESC LIMIT 1"),
                {"conversation": next_conversation["conversation_id"]}).one()
            assert rejected.state == "version_rejected" and rejected.answer_text is None
    finally:
        public_engine.dispose()


def _assistant(factory, owner):
    with factory.begin() as session:
        set_owner_identity(session, owner)
        row = Assistant(owner_id=owner, **payload())
        session.add(row)
        session.flush()
        return row.id


def _fingerprint(factory, owner, assistant):
    with factory.begin() as session:
        set_owner_identity(session, owner)
        row = session.get(Assistant, assistant)
        return PublicationService(session, embedding_provider="openai",
            embedding_model="text-embedding-3-small").fingerprint(owner, row)[0]


def test_publication_owner_isolation_and_snapshot_immutability(p4_db):
    admin, runtime = p4_db
    factory = sessionmaker(runtime, expire_on_commit=False)
    owner_a, owner_b = uuid4(), uuid4()
    assistant = _assistant(factory, owner_a)
    fingerprint = _fingerprint(factory, owner_a, assistant)
    with factory.begin() as session:
        set_owner_identity(session, owner_a)
        assert session.scalar(text("SELECT current_setting('app.owner_id',true)")) == str(owner_a)
        publication, snapshot, replay = PublicationService(
            session, embedding_provider="openai", embedding_model="text-embedding-3-small"
        ).publish(owner_a, assistant, expected_fingerprint=fingerprint,
                  expected_version=None, idempotency_key="pg-p4-publish-a")
        assert not replay and snapshot.state == "published"
        public_id, snapshot_id = publication.public_id, snapshot.id
    with factory.begin() as session:
        set_owner_identity(session, owner_b)
        assert session.scalar(text("SELECT count(*) FROM public.assistant_publications")) == 0
        assert session.scalar(text("SELECT count(*) FROM public.published_snapshots")) == 0
    with pytest.raises(DBAPIError), factory.begin() as session:
        set_owner_identity(session, owner_a)
        session.execute(text("UPDATE public.published_snapshots SET config='{}'::jsonb WHERE id=:id"),
                        {"id": snapshot_id})
    with admin.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM public.published_snapshots WHERE id=:id AND state='published'"),
                           {"id": snapshot_id}) == 1
        assert conn.scalar(text("SELECT public_id FROM public.assistant_publications WHERE assistant_id=:id"),
                           {"id": assistant}) == public_id


def test_p403_publication_status_and_same_content_deduplication(p4_db):
    _, runtime = p4_db
    factory = sessionmaker(runtime, expire_on_commit=False)
    owner, other = uuid4(), uuid4()
    assistant = _assistant(factory, owner)
    service_options = {"embedding_provider": "openai", "embedding_model": "text-embedding-3-small"}

    with factory.begin() as session:
        set_owner_identity(session, owner)
        service = PublicationService(session, **service_options)
        before = service.status(owner, assistant)
        assert before["readiness"] == "fallback_only"
        assert before["published"] is False and before["has_changes"] is True
        publication, first, replayed = service.publish(owner, assistant,
            expected_fingerprint=before["draft_fingerprint"], expected_version=None,
            idempotency_key="p403-first")
        assert not replayed and first.version == 1
        first_id, public_id = first.id, publication.public_id

    with factory.begin() as session:
        set_owner_identity(session, owner)
        service = PublicationService(session, **service_options)
        current = service.status(owner, assistant)
        assert current["published"] is True and current["public_id"] == public_id
        assert current["version"] == 1 and current["readiness"] == "fallback_only"
        assert current["has_changes"] is False
        _, same, replayed = service.publish(owner, assistant,
            expected_fingerprint=current["draft_fingerprint"], expected_version=1,
            idempotency_key="p403-same-content")
        assert replayed and same.id == first_id

    with factory.begin() as session:
        set_owner_identity(session, owner)
        assistant_row = session.get(Assistant, assistant)
        assistant_row.fallback_message = "Changed draft fallback"

    with factory.begin() as session:
        set_owner_identity(session, owner)
        assert PublicationService(session, **service_options).status(owner, assistant)["has_changes"] is True
        with pytest.raises(PublicationFailure, match="not_found"):
            PublicationService(session, **service_options).status(other, assistant)


def test_published_snapshot_pins_ready_index_without_copying_vectors(p4_db):
    admin, runtime = p4_db
    factory = sessionmaker(runtime, expire_on_commit=False)
    owner, assistant, file_id, index_id = uuid4(), None, uuid4(), uuid4()
    assistant = _assistant(factory, owner)
    extracted = "Synthetic business facts for source pinning."
    content_hash = sha256(b"synthetic docx bytes").hexdigest()
    source_hash = sha256(extracted.encode()).hexdigest()
    manifest = sha256(json.dumps([{
        "file_id": str(file_id), "content_sha256": content_hash,
        "extraction_version": "extract-v1", "text_sha256": source_hash,
    }], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    now = datetime.now(timezone.utc)
    seed_factory = sessionmaker(admin, expire_on_commit=False)
    with seed_factory.begin() as session:
        session.add(KnowledgeFile(id=file_id, owner_id=owner, assistant_id=assistant,
            slot_number=1, original_filename="synthetic.docx", file_format="docx",
            size_bytes=128, content_sha256=content_hash,
            object_key=f"owners/{owner}/assistants/{assistant}/files/{file_id}/original.docx",
            processing_state="extracted", operation_id=uuid4(),
            lease_expires_at=now + timedelta(minutes=1), cleanup_state="not_needed"))
        session.flush()
        session.add(KnowledgeFileText(file_id=file_id, assistant_id=assistant,
            owner_id=owner, extracted_text=extracted, extraction_version="extract-v1"))
        session.add(KnowledgeIndex(id=index_id, owner_id=owner, assistant_id=assistant,
            version=1, idempotency_key=uuid4(), manifest_sha256=manifest,
            embedding_provider="openai", embedding_model="text-embedding-3-small",
            vector_dimension=768, tokenizer_version="cl100k_base",
            chunker_version="fixed-600-100-v1", state="ready", operation_id=uuid4(),
            lease_expires_at=now + timedelta(minutes=1), total_chunks=1,
            completed_chunks=1, ready_at=now))
        session.flush()
        session.add(KnowledgeIndexSource(index_id=index_id, file_id=file_id,
            assistant_id=assistant, owner_id=owner, extraction_version="extract-v1",
            source_sha256=source_hash))
        session.flush()
        session.add(KnowledgeChunk(id=uuid4(), index_id=index_id, owner_id=owner,
            assistant_id=assistant, file_id=file_id, ordinal=0,
            extraction_version="extract-v1", chunker_version="fixed-600-100-v1",
            source_sha256=source_hash, start_offset=0, end_offset=len(extracted),
            token_count=8, text_sha256=source_hash, chunk_text=extracted,
            embedding=tuple([1.0] + [0.0] * 767)))
        row = session.get(Assistant, assistant)
        row.active_knowledge_index_id = index_id
    fingerprint = _fingerprint(factory, owner, assistant)
    with factory.begin() as session:
        set_owner_identity(session, owner)
        publication, snapshot, _ = PublicationService(session,
            embedding_provider="openai", embedding_model="text-embedding-3-small").publish(
            owner, assistant, expected_fingerprint=fingerprint, expected_version=None,
            idempotency_key="source-pin-test")
        assert snapshot.source_count == 1 and snapshot.knowledge_index_id == index_id
        snapshot_id = snapshot.id
    with admin.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM public.knowledge_chunks WHERE index_id=:id"), {"id": index_id}) == 1
        assert conn.scalar(text("SELECT count(*) FROM public.published_sources WHERE snapshot_id=:id AND index_id=:index"),
                           {"id": snapshot_id, "index": index_id}) == 1
        assert conn.scalar(text("SELECT count(*) FROM public.published_snapshots WHERE id=:id AND manifest_sha256=:manifest"),
                           {"id": snapshot_id, "manifest": manifest}) == 1


def test_single_active_snapshot_under_concurrent_publish_requests(p4_db):
    _admin, runtime = p4_db
    factory = sessionmaker(runtime, expire_on_commit=False)
    owner = uuid4()
    assistant = _assistant(factory, owner)
    fingerprint = _fingerprint(factory, owner, assistant)

    def publish(key):
        try:
            with factory.begin() as session:
                set_owner_identity(session, owner)
                return PublicationService(session, embedding_provider="openai",
                    embedding_model="text-embedding-3-small").publish(owner, assistant,
                    expected_fingerprint=fingerprint, expected_version=None,
                    idempotency_key=key)[1].id
        except PublicationFailure as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, ("concurrent-a", "concurrent-b")))
    assert sum(not isinstance(result, str) for result in results) == 1
    assert results.count("publication_changed") == 1
    with factory.begin() as session:
        set_owner_identity(session, owner)
        assert session.scalar(text("SELECT count(*) FROM public.assistant_publications WHERE assistant_id=:id AND active_snapshot_id IS NOT NULL"),
                              {"id": assistant}) == 1


def test_public_runtime_sees_only_active_snapshot_and_cannot_read_draft_or_ledger(p4_db):
    admin, runtime = p4_db
    factory = sessionmaker(runtime, expire_on_commit=False)
    owner = uuid4()
    assistant = _assistant(factory, owner)
    fingerprint = _fingerprint(factory, owner, assistant)
    with factory.begin() as session:
        set_owner_identity(session, owner)
        publication, snapshot, _ = PublicationService(
            session, embedding_provider="openai", embedding_model="text-embedding-3-small"
        ).publish(owner, assistant, expected_fingerprint=fingerprint,
                  expected_version=None, idempotency_key="public-read-test")
        public_id, snapshot_id = publication.public_id, snapshot.id
    public_engine, public_factory = _public_role_factory(admin)
    try:
        with public_factory.begin() as session:
            assert session.scalar(text("SELECT current_user")) == "assistant_public_runtime"
            session.execute(text("SELECT set_config('app.public_id',:v,true)"), {"v": str(public_id)})
            session.execute(text("SELECT set_config('app.snapshot_id',:v,true)"), {"v": str(snapshot_id)})
            assert session.scalar(text("SELECT count(*) FROM public.published_snapshots")) == 1
            assert session.scalar(text("SELECT count(*) FROM public.assistant_publications")) == 1
            session.execute(text("SELECT set_config('app.snapshot_id',:v,true)"), {"v": str(uuid4())})
            assert session.scalar(text("SELECT count(*) FROM public.published_snapshots")) == 0
        with pytest.raises(DBAPIError), public_factory.begin() as session:
            session.execute(text("SELECT id FROM public.assistants"))
        with pytest.raises(DBAPIError), public_factory.begin() as session:
            session.execute(text("SELECT * FROM ai_accounting.budget_attempts"))
        with admin.connect() as conn:
            assert not conn.scalar(text("SELECT has_table_privilege('assistant_public_runtime','public.assistants','SELECT')"))
            assert not conn.scalar(text("SELECT has_table_privilege('assistant_public_runtime','ai_accounting.budget_attempts','SELECT')"))
            assert not conn.scalar(text("SELECT has_table_privilege('assistant_runtime','ai_accounting.budget_attempts','SELECT')"))
            assert not conn.scalar(text("SELECT has_table_privilege('assistant_public_runtime','public.assistant_publications','UPDATE')"))
            assert not conn.scalar(text("SELECT has_table_privilege('assistant_runtime','public.published_snapshots','UPDATE')"))
            assert not conn.scalar(text("SELECT has_table_privilege('assistant_runtime','public.published_snapshots','DELETE')"))
            assert not conn.scalar(text("SELECT has_table_privilege('assistant_runtime','public.published_sources','UPDATE')"))
            assert not conn.scalar(text("SELECT has_table_privilege('assistant_runtime','public.published_sources','DELETE')"))
            assert not conn.scalar(text("SELECT has_table_privilege('assistant_budget_executor','public.assistants','SELECT')"))
            for role in ("anon", "authenticated", "service_role"):
                for table in ("assistant_publications", "published_snapshots", "published_sources",
                              "publication_requests", "visitor_conversations", "visitor_turns"):
                    assert not conn.scalar(text("SELECT has_table_privilege(:role,:table,'SELECT') OR has_table_privilege(:role,:table,'INSERT') OR has_table_privilege(:role,:table,'UPDATE') OR has_table_privilege(:role,:table,'DELETE')"),
                                           {"role": role, "table": "public." + table})
            assert conn.scalar(text("SELECT has_function_privilege('assistant_runtime','ai_accounting.reserve_attempt(uuid,uuid,text,text,uuid,bigint,bigint,text)','EXECUTE')"))
            assert conn.scalar(text("SELECT has_function_privilege('assistant_public_runtime','ai_accounting.reserve_attempt(uuid,uuid,text,text,uuid,bigint,bigint,text)','EXECUTE')"))
            functions = conn.execute(text("""SELECT p.prosecdef, p.proconfig,
                r.rolname, EXISTS (SELECT 1 FROM aclexplode(p.proacl) acl WHERE acl.grantee=0 AND acl.privilege_type='EXECUTE')
                FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                JOIN pg_roles r ON r.oid=p.proowner
                WHERE n.nspname='ai_accounting' AND p.proname IN
                  ('reserve_attempt','mark_dispatched','settle_attempt','cancel_undispatched')""")).all()
            assert len(functions) == 4
            assert all(definer and config == ["search_path=pg_catalog"]
                       and role == "assistant_budget_executor" and not public_execute
                       for definer, config, role, public_execute in functions)
    finally:
        public_engine.dispose()


def test_accounting_atomic_daily_budget_settlement_and_uncertainty(p4_db):
    admin, runtime = p4_db
    owner, assistant = uuid4(), uuid4()
    price_id, operation = uuid4(), uuid4()
    scope = sha256(f"{owner}:{assistant}".encode()).hexdigest()
    today = datetime.now(timezone.utc).date()
    with admin.begin() as conn:
        # This exact database is a disposable integration-test database. Reset
        # only the accounting fixtures created by this test module.
        conn.execute(text("DELETE FROM ai_accounting.budget_day_holds"))
        conn.execute(text("DELETE FROM ai_accounting.budget_attempts"))
        conn.execute(text("DELETE FROM ai_accounting.budget_operations"))
        conn.execute(text("DELETE FROM ai_accounting.budget_days"))
        conn.execute(text("DELETE FROM ai_accounting.price_versions"))
        conn.execute(text("INSERT INTO ai_accounting.price_versions(id,provider,model,input_microusd_per_million,output_microusd_per_million,embedding_microusd_per_million,message_cap_microusd,index_cap_microusd,daily_cap_microusd,valid_from) VALUES (:id,'openai','text-embedding-3-small',10000000,10000000,10000000,10000,100000,1000000,now())"), {"id": price_id})
        conn.execute(text("INSERT INTO ai_accounting.budget_days(day_utc,charged_microusd) VALUES (:day,990000) ON CONFLICT(day_utc) DO UPDATE SET charged_microusd=990000,held_microusd=0"), {"day": today})

    rolled_back_attempt = uuid4()
    with pytest.raises(RuntimeError, match="rollback"), runtime.begin() as conn:
        conn.execute(text("SELECT set_config('app.owner_id',:v,true)"), {"v": str(owner)})
        conn.execute(text("SELECT set_config('app.assistant_id',:v,true)"), {"v": str(assistant)})
        assert conn.scalar(text("SELECT ai_accounting.reserve_attempt(:op,:attempt,'index_embedding',:scope,:price,1000,0,:request)"),
            {"op": operation, "attempt": rolled_back_attempt, "scope": scope, "price": price_id,
             "request": sha256(str(rolled_back_attempt).encode()).hexdigest()})
        raise RuntimeError("rollback")
    with admin.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM ai_accounting.budget_attempts WHERE id=:id"), {"id": rolled_back_attempt}) == 0

    def reserve(attempt):
        engine = create_engine(make_url(os.environ["PHASE1_LOCAL_RUNTIME_URL"]), hide_parameters=True)
        try:
            with engine.begin() as conn:
                conn.execute(text("SELECT set_config('app.owner_id',:v,true)"), {"v": str(owner)})
                conn.execute(text("SELECT set_config('app.assistant_id',:v,true)"), {"v": str(assistant)})
                return conn.scalar(text("SELECT ai_accounting.reserve_attempt(:op,:attempt,'index_embedding',:scope,:price,1000,0,:request)"),
                    {"op": operation, "attempt": attempt, "scope": scope, "price": price_id,
                     "request": sha256(str(attempt).encode()).hexdigest()})
        except DBAPIError as exc:
            return f"db_error:{getattr(exc.orig, 'sqlstate', 'unknown')}:{getattr(getattr(exc.orig, 'diag', None), 'message_primary', 'database_error')}"
        finally:
            engine.dispose()

    attempts = [uuid4(), uuid4()]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, attempts))
    assert outcomes.count(True) == 1
    assert sum(isinstance(value, str) and value.startswith("db_error:") for value in outcomes) == 1, outcomes
    accepted = attempts[outcomes.index(True)]
    with runtime.begin() as conn:
        conn.execute(text("SELECT set_config('app.owner_id',:v,true)"), {"v": str(owner)})
        conn.execute(text("SELECT set_config('app.assistant_id',:v,true)"), {"v": str(assistant)})
        assert conn.scalar(text("SELECT ai_accounting.mark_dispatched(:id)"), {"id": accepted}) is True
        assert conn.scalar(text("SELECT ai_accounting.settle_attempt(:id,400,0)"), {"id": accepted}) is True
        assert conn.scalar(text("SELECT ai_accounting.settle_attempt(:id,400,0)"), {"id": accepted}) is True
        assert not conn.scalar(text("SELECT ai_accounting.settle_attempt(:id,401,0)"), {"id": accepted})
    with admin.connect() as conn:
        assert conn.scalar(text("SELECT charged_microusd FROM ai_accounting.budget_days WHERE day_utc=:day"), {"day": today}) == 994000
        assert conn.scalar(text("SELECT held_microusd FROM ai_accounting.budget_days WHERE day_utc=:day+1"), {"day": today}) == 0
        assert conn.scalar(text("SELECT charged_microusd FROM ai_accounting.budget_days WHERE day_utc=:day+1"), {"day": today}) == 4000
    with runtime.begin() as conn:
        conn.execute(text("SELECT set_config('app.owner_id',:v,true)"), {"v": str(owner)})
        conn.execute(text("SELECT set_config('app.assistant_id',:v,true)"), {"v": str(assistant)})
        denied = uuid4()
        assert not conn.scalar(text("SELECT ai_accounting.reserve_attempt(:op,:attempt,'index_embedding',:scope,:price,10000,0,:request)"),
            {"op": operation, "attempt": denied, "scope": scope, "price": price_id,
             "request": sha256(str(denied).encode()).hexdigest()})


def test_dispatched_unknown_attempt_retains_hold_and_blocks_operation_reuse(p4_db):
    admin, runtime = p4_db
    owner, assistant, attempt, operation = uuid4(), uuid4(), uuid4(), uuid4()
    scope = sha256(f"{owner}:{assistant}".encode()).hexdigest()
    price_id = uuid4()
    with admin.begin() as conn:
        conn.execute(text("UPDATE ai_accounting.budget_days SET charged_microusd=0,held_microusd=0"))
        conn.execute(text("INSERT INTO ai_accounting.price_versions(id,provider,model,input_microusd_per_million,output_microusd_per_million,embedding_microusd_per_million,message_cap_microusd,index_cap_microusd,daily_cap_microusd,valid_from) VALUES (:id,'openai','text-embedding-3-small',10000000,10000000,10000000,10000,100000,1000000,now())"), {"id": price_id})
    with runtime.begin() as conn:
        conn.execute(text("SELECT set_config('app.owner_id',:v,true)"), {"v": str(owner)})
        conn.execute(text("SELECT set_config('app.assistant_id',:v,true)"), {"v": str(assistant)})
        assert conn.scalar(text("SELECT ai_accounting.reserve_attempt(:op,:attempt,'index_embedding',:scope,:price,1000,0,:request)"),
            {"op": operation, "attempt": attempt, "scope": scope, "price": price_id,
             "request": sha256(str(attempt).encode()).hexdigest()})
        assert conn.scalar(text("SELECT ai_accounting.mark_dispatched(:id)"), {"id": attempt})
        assert not conn.scalar(text("SELECT ai_accounting.reserve_attempt(:op,:next,'index_embedding',:scope,:price,1000,0,:request)"),
            {"op": operation, "next": uuid4(), "scope": scope, "price": price_id,
             "request": sha256(uuid4().bytes).hexdigest()})
    with admin.connect() as conn:
        assert conn.scalar(text("SELECT state FROM ai_accounting.budget_attempts WHERE id=:id"), {"id": attempt}) == "dispatched"
        assert conn.scalar(text("SELECT held_microusd FROM ai_accounting.budget_attempts WHERE id=:id"), {"id": attempt}) == 10000


def test_publication_failure_rolls_back_all_snapshot_rows(p4_db):
    admin, runtime = p4_db
    factory = sessionmaker(runtime, expire_on_commit=False)
    owner = uuid4()
    assistant = _assistant(factory, owner)
    fingerprint = _fingerprint(factory, owner, assistant)
    with admin.begin() as conn:
        conn.execute(text("""CREATE FUNCTION public.test_p4_abort_publication_request() RETURNS trigger
            LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RAISE EXCEPTION 'test rollback'; END $$"""))
        conn.execute(text("CREATE TRIGGER test_p4_abort_request BEFORE INSERT ON public.publication_requests FOR EACH ROW EXECUTE FUNCTION public.test_p4_abort_publication_request()"))
    try:
        with pytest.raises(DBAPIError), factory.begin() as session:
            set_owner_identity(session, owner)
            PublicationService(session, embedding_provider="openai",
                embedding_model="text-embedding-3-small").publish(owner, assistant,
                expected_fingerprint=fingerprint, expected_version=None,
                idempotency_key="rollback-publish")
        with admin.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM public.assistant_publications WHERE assistant_id=:id"),
                               {"id": assistant}) == 0
            assert conn.scalar(text("SELECT count(*) FROM public.published_snapshots WHERE assistant_id=:id"),
                               {"id": assistant}) == 0
    finally:
        with admin.begin() as conn:
            conn.execute(text("DROP TRIGGER IF EXISTS test_p4_abort_request ON public.publication_requests"))
            conn.execute(text("DROP FUNCTION IF EXISTS public.test_p4_abort_publication_request()"))
