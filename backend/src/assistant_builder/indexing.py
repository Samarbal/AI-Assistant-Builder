"""Durable, owner-scoped versioned indexing. No retrieval/API routes in this module."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from sqlalchemy import select
from sqlalchemy.orm import Session

from .chunking import Chunk, Chunker, ChunkingError, ChunkingLimitExceeded, SourceText
from .db import set_owner_identity
from .embeddings import EmbeddingFailure, EmbeddingProvider
from .models import (Assistant, KnowledgeFile, KnowledgeFileText, KnowledgeChunk,
                     KnowledgeIndex, KnowledgeIndexBatch, KnowledgeIndexSource)

MAX_BATCH_INPUTS = 8
MAX_BATCH_TOKENS = 4800
MAX_INDEX_CHUNKS = 200
INDEX_LEASE = timedelta(seconds=60)
MAX_INDEX_COST_MICRO_USD = 100_000  # $0.10, contract ceiling.


class IndexingFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _as_utc(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class IndexStatus:
    index_id: UUID
    state: str
    completed_chunks: int
    total_chunks: int
    next_batch: int | None
    error_code: str | None = None


@dataclass(frozen=True)
class PreparationStatus:
    """Owner-scoped readiness derived from current files and index manifests."""

    state: str
    operation_id: UUID | None
    completed_chunks: int
    total_chunks: int
    eligible_files: int
    error_code: str | None = None


def split_embedding_batches(chunks: tuple[Chunk, ...], tokenizer, *,
                            max_inputs=MAX_BATCH_INPUTS, max_tokens=MAX_BATCH_TOKENS):
    if not 1 <= max_inputs <= MAX_BATCH_INPUTS or not 1 <= max_tokens <= MAX_BATCH_TOKENS:
        raise IndexingFailure("index_configuration")
    batches, current, tokens = [], [], 0
    for chunk in chunks:
        count = len(tokenizer.encode(chunk.text))
        if count <= 0 or count > max_tokens or count > 600:
            raise IndexingFailure("index_input_limit")
        if current and (len(current) >= max_inputs or tokens + count > max_tokens):
            batches.append(tuple(current))
            current, tokens = [], 0
        current.append(chunk)
        tokens += count
    if current:
        batches.append(tuple(current))
    return tuple(batches)


def sha_text(text):
    return sha256(text.encode("utf-8")).hexdigest()


class VersionedIndexService:
    """start() records an immutable manifest and batches; advance() commits one batch.

    `sessions` is the restricted runtime session factory. Every DB transaction sets
    verified owner identity before protected reads. Provider I/O runs with no DB
    transaction open. A route is intentionally not registered yet.
    """
    def __init__(self, sessions, chunker: Chunker, embedding_provider: EmbeddingProvider,
                 *, tokenizer, embedding_model: str, vector_dimension=768,
                 embedding_provider_name="openai", clock=lambda: datetime.now(timezone.utc)):
        if vector_dimension != 768 or embedding_model != "text-embedding-3-small":
            raise IndexingFailure("index_configuration")
        self.sessions, self.chunker, self.provider, self.tokenizer = sessions, chunker, embedding_provider, tokenizer
        self.embedding_model, self.dimension = embedding_model, vector_dimension
        self.embedding_provider_name, self.clock = embedding_provider_name, clock

    def _set_owner(self, session, owner):
        if session.bind.dialect.name == "postgresql":
            set_owner_identity(session, owner)

    def _sources(self, session, owner, assistant):
        assistant_row = session.scalar(select(Assistant).where(
            Assistant.id == assistant, Assistant.owner_id == owner).with_for_update())
        if assistant_row is None:
            raise IndexingFailure("assistant_not_found")
        files = session.scalars(select(KnowledgeFile).where(
            KnowledgeFile.owner_id == owner, KnowledgeFile.assistant_id == assistant,
            KnowledgeFile.removed_at.is_(None)).order_by(KnowledgeFile.id)).all()
        if any(f.processing_state in {"accepted", "processing"} for f in files):
            raise IndexingFailure("knowledge_not_ready")
        rows = session.execute(select(KnowledgeFile, KnowledgeFileText).join(
            KnowledgeFileText, KnowledgeFileText.file_id == KnowledgeFile.id).where(
            KnowledgeFile.owner_id == owner, KnowledgeFile.assistant_id == assistant,
            KnowledgeFile.removed_at.is_(None), KnowledgeFile.processing_state == "extracted"
        ).order_by(KnowledgeFile.id)).all()
        extracted_ids = {file.id for file, _ in rows}
        expected_ids = {file.id for file in files if file.processing_state == "extracted"}
        if extracted_ids != expected_ids:
            raise IndexingFailure("knowledge_not_ready")
        sources = tuple(SourceText(owner, assistant, file.id, extracted.extraction_version,
                                   extracted.extracted_text) for file, extracted in rows)
        manifest_items = [{"file_id": str(file.id), "content_sha256": file.content_sha256,
                           "extraction_version": extracted.extraction_version,
                           "text_sha256": sha_text(extracted.extracted_text)}
                          for file, extracted in rows]
        manifest = sha256(json.dumps(manifest_items, sort_keys=True,
                            separators=(",", ":")).encode()).hexdigest()
        return assistant_row, rows, sources, manifest

    def start(self, owner: UUID, assistant: UUID, idempotency_key: UUID):
        if not all(isinstance(v, UUID) for v in (owner, assistant, idempotency_key)):
            raise IndexingFailure("index_invalid_request")
        with self.sessions.begin() as session:
            self._set_owner(session, owner)
            parent, rows, sources, manifest = self._sources(session, owner, assistant)
            existing = session.scalar(select(KnowledgeIndex).where(
                KnowledgeIndex.owner_id == owner, KnowledgeIndex.assistant_id == assistant,
                KnowledgeIndex.idempotency_key == idempotency_key))
            if existing:
                return self._status(session, existing)
            uncertain = session.scalar(select(KnowledgeIndexBatch.id).join(
                KnowledgeIndex, KnowledgeIndex.id == KnowledgeIndexBatch.index_id).where(
                    KnowledgeIndex.owner_id == owner,
                    KnowledgeIndex.assistant_id == assistant,
                    KnowledgeIndexBatch.state == "uncertain").limit(1))
            if uncertain is not None:
                raise IndexingFailure("provider_attempt_uncertain")
            if parent.active_knowledge_index_id is not None:
                active = session.scalar(select(KnowledgeIndex).where(
                    KnowledgeIndex.id == parent.active_knowledge_index_id,
                    KnowledgeIndex.owner_id == owner,
                    KnowledgeIndex.assistant_id == assistant,
                ).with_for_update())
                if (active is None or active.state != "ready"
                        or active.manifest_sha256 != manifest
                        or active.embedding_provider != self.embedding_provider_name
                        or active.embedding_model != self.embedding_model
                        or active.vector_dimension != self.dimension
                        or active.tokenizer_version != self.tokenizer.fingerprint
                        or active.chunker_version != self.chunker.fingerprint):
                    parent.active_knowledge_index_id = None
            equivalent = session.scalar(select(KnowledgeIndex).where(
                KnowledgeIndex.owner_id == owner, KnowledgeIndex.assistant_id == assistant,
                KnowledgeIndex.state == "ready", KnowledgeIndex.manifest_sha256 == manifest,
                KnowledgeIndex.embedding_provider == self.embedding_provider_name,
                KnowledgeIndex.embedding_model == self.embedding_model,
                KnowledgeIndex.vector_dimension == self.dimension,
                KnowledgeIndex.tokenizer_version == self.tokenizer.fingerprint,
                KnowledgeIndex.chunker_version == self.chunker.fingerprint).order_by(
                    KnowledgeIndex.version.desc()))
            if equivalent:
                parent.active_knowledge_index_id = equivalent.id
                return self._status(session, equivalent)
            building = session.scalar(select(KnowledgeIndex).where(
                KnowledgeIndex.owner_id == owner, KnowledgeIndex.assistant_id == assistant,
                KnowledgeIndex.state == "building"))
            if building:
                raise IndexingFailure("preparation_busy")
            try:
                chunks = self.chunker.chunk(sources)
            except ChunkingLimitExceeded:
                raise IndexingFailure("index_resource_limit") from None
            except ChunkingError:
                raise IndexingFailure("source_chunking_failure") from None
            if not chunks:
                raise IndexingFailure("no_knowledge")
            if len(chunks) > MAX_INDEX_CHUNKS:
                raise IndexingFailure("index_resource_limit")
            batches = split_embedding_batches(chunks, self.tokenizer)
            next_version = (session.scalar(select(KnowledgeIndex.version).where(
                KnowledgeIndex.owner_id == owner, KnowledgeIndex.assistant_id == assistant
            ).order_by(KnowledgeIndex.version.desc()).limit(1)) or 0) + 1
            now = self.clock()
            index = KnowledgeIndex(id=uuid4(), owner_id=owner, assistant_id=assistant,
                version=next_version, idempotency_key=idempotency_key, manifest_sha256=manifest,
                embedding_provider=self.embedding_provider_name, embedding_model=self.embedding_model,
                vector_dimension=self.dimension, tokenizer_version=self.tokenizer.fingerprint,
                chunker_version=self.chunker.fingerprint, state="building", operation_id=uuid4(),
                lease_expires_at=now + INDEX_LEASE, total_chunks=len(chunks), completed_chunks=0)
            session.add(index)
            session.flush()
            for file, extracted in rows:
                session.add(KnowledgeIndexSource(index_id=index.id, file_id=file.id,
                    assistant_id=assistant, owner_id=owner,
                    extraction_version=extracted.extraction_version,
                    source_sha256=sha_text(extracted.extracted_text)))
            for number, batch in enumerate(batches):
                token_count = sum(len(self.tokenizer.encode(c.text)) for c in batch)
                # OpenAI's validated rate: $0.02 / 1M tokens = 0.02 micro-USD/token.
                reserve_micro = math.ceil(token_count * 0.02)
                index.reserved_cost_microusd += reserve_micro
                session.add(KnowledgeIndexBatch(id=uuid4(), index_id=index.id,
                    assistant_id=assistant, owner_id=owner, batch_number=number,
                    idempotency_key=uuid4(), request_sha256=sha256("".join(str(c.id) for c in batch).encode()).hexdigest(),
                    chunk_ids=[str(c.id) for c in batch], reserved_tokens=token_count,
                    reserved_cost_microusd=reserve_micro, state="pending", operation_id=uuid4(),
                    lease_expires_at=now + INDEX_LEASE))
            if index.reserved_cost_microusd > MAX_INDEX_COST_MICRO_USD:
                raise IndexingFailure("index_cost_limit")
            return self._status(session, index)

    def _load_chunks(self, session, owner, assistant, index):
        parent, rows, sources, manifest = self._sources(session, owner, assistant)
        chunks = self.chunker.chunk(sources)
        return manifest, {str(chunk.id): chunk for chunk in chunks}

    @staticmethod
    def _status(session, index):
        pending = session.scalar(select(KnowledgeIndexBatch.batch_number).where(
            KnowledgeIndexBatch.index_id == index.id,
            KnowledgeIndexBatch.state == "pending").order_by(KnowledgeIndexBatch.batch_number).limit(1))
        return IndexStatus(index.id, index.state, index.completed_chunks,
                           index.total_chunks, pending, index.error_code)

    def status(self, owner: UUID, assistant: UUID) -> PreparationStatus:
        """Report current readiness without changing pointers or invoking providers."""
        if not isinstance(owner, UUID) or not isinstance(assistant, UUID):
            raise IndexingFailure("index_invalid_request")
        with self.sessions.begin() as session:
            self._set_owner(session, owner)
            parent = session.scalar(select(Assistant).where(
                Assistant.id == assistant, Assistant.owner_id == owner))
            if parent is None:
                raise IndexingFailure("assistant_not_found")

            files = session.scalars(select(KnowledgeFile).where(
                KnowledgeFile.owner_id == owner, KnowledgeFile.assistant_id == assistant,
                KnowledgeFile.removed_at.is_(None)).order_by(KnowledgeFile.id)).all()
            eligible_files = sum(file.processing_state == "extracted" for file in files)
            pending_files = any(file.processing_state in {"accepted", "processing"} for file in files)

            building = session.scalar(select(KnowledgeIndex).where(
                KnowledgeIndex.owner_id == owner, KnowledgeIndex.assistant_id == assistant,
                KnowledgeIndex.state == "building").order_by(KnowledgeIndex.version.desc()).limit(1))
            if pending_files:
                return PreparationStatus(
                    "blocked", building.id if building else None,
                    building.completed_chunks if building else 0,
                    building.total_chunks if building else 0,
                    eligible_files, "file_processing")

            try:
                parent, _, sources, manifest = self._sources(session, owner, assistant)
            except IndexingFailure as exc:
                if exc.code == "knowledge_not_ready":
                    return PreparationStatus("blocked", building.id if building else None,
                        building.completed_chunks if building else 0,
                        building.total_chunks if building else 0,
                        eligible_files, "extracted_text_unavailable")
                raise

            if not sources:
                return PreparationStatus("no_knowledge", None, 0, 0, 0)

            if building is not None:
                return PreparationStatus("preparing", building.id,
                    building.completed_chunks, building.total_chunks, eligible_files,
                    "source_changed" if building.manifest_sha256 != manifest else None)

            active = None
            if parent.active_knowledge_index_id is not None:
                active = session.scalar(select(KnowledgeIndex).where(
                    KnowledgeIndex.id == parent.active_knowledge_index_id,
                    KnowledgeIndex.owner_id == owner, KnowledgeIndex.assistant_id == assistant))
            if active is not None:
                matches = (
                    active.state == "ready" and active.manifest_sha256 == manifest
                    and active.embedding_provider == self.embedding_provider_name
                    and active.embedding_model == self.embedding_model
                    and active.vector_dimension == self.dimension
                    and active.tokenizer_version == self.tokenizer.fingerprint
                    and active.chunker_version == self.chunker.fingerprint
                )
                if matches:
                    return PreparationStatus("ready", active.id, active.completed_chunks,
                        active.total_chunks, eligible_files)

            uncertain = session.execute(select(KnowledgeIndex, KnowledgeIndexBatch).join(
                KnowledgeIndexBatch, KnowledgeIndexBatch.index_id == KnowledgeIndex.id).where(
                    KnowledgeIndex.owner_id == owner,
                    KnowledgeIndex.assistant_id == assistant,
                    KnowledgeIndexBatch.state == "uncertain").order_by(
                        KnowledgeIndex.version.desc(), KnowledgeIndexBatch.batch_number).limit(1)).first()
            if uncertain is not None:
                index, _batch = uncertain
                return PreparationStatus("failed", index.id, index.completed_chunks,
                    index.total_chunks, eligible_files, "provider_attempt_uncertain")

            failed = session.scalar(select(KnowledgeIndex).where(
                KnowledgeIndex.owner_id == owner, KnowledgeIndex.assistant_id == assistant,
                KnowledgeIndex.state == "failed", KnowledgeIndex.manifest_sha256 == manifest
            ).order_by(KnowledgeIndex.version.desc()).limit(1))
            if failed is not None:
                return PreparationStatus("failed", failed.id, failed.completed_chunks,
                    failed.total_chunks, eligible_files, failed.error_code)
            return PreparationStatus("needs_preparation", None, 0, 0, eligible_files,
                "source_changed" if active is not None else None)

    async def advance(self, owner: UUID, assistant: UUID, index_id: UUID,
                      *, idempotency_key: UUID | None = None):
        # Claim a single batch and commit the durable lease before provider I/O.
        if idempotency_key is not None and not isinstance(idempotency_key, UUID):
            raise IndexingFailure("index_invalid_request")
        with self.sessions.begin() as session:
            self._set_owner(session, owner)
            index = session.scalar(select(KnowledgeIndex).where(
                KnowledgeIndex.id == index_id, KnowledgeIndex.owner_id == owner,
                KnowledgeIndex.assistant_id == assistant).with_for_update())
            if index is None:
                raise IndexingFailure("index_not_found")
            if index.state == "ready":
                return self._status(session, index)
            if index.state != "building":
                raise IndexingFailure("index_lease_expired")
            inflight = session.scalar(select(KnowledgeIndexBatch.id).where(
                KnowledgeIndexBatch.index_id == index.id,
                KnowledgeIndexBatch.state == "inflight").limit(1))
            if inflight is not None:
                raise IndexingFailure("preparation_busy")
            now = self.clock()
            if _as_utc(index.lease_expires_at) <= _as_utc(now):
                # A previous DB permission/transaction failure can leave a
                # building index with a pending batch even though no provider
                # attempt began. Resume only that provably unattempted work;
                # any uncertain/failed/inflight or previously attempted pending
                # batch still requires the explicit recovery path.
                batch_states = session.execute(select(
                    KnowledgeIndexBatch.state, KnowledgeIndexBatch.attempts
                ).where(KnowledgeIndexBatch.index_id == index.id)).all()
                safe_to_resume = (
                    any(state == "pending" and attempts == 0
                        for state, attempts in batch_states)
                    and all(state in {"pending", "completed"}
                            and (state != "pending" or attempts == 0)
                            for state, attempts in batch_states)
                )
                if not safe_to_resume:
                    raise IndexingFailure("index_lease_expired")
                index.operation_id = uuid4()
                index.lease_expires_at = now + INDEX_LEASE
            if idempotency_key is not None:
                previous = session.scalar(select(KnowledgeIndexBatch).where(
                    KnowledgeIndexBatch.index_id == index.id,
                    KnowledgeIndexBatch.idempotency_key == idempotency_key))
                if previous is not None:
                    if previous.state == "completed":
                        return self._status(session, index)
                    if previous.state == "inflight":
                        raise IndexingFailure("preparation_busy")
                    raise IndexingFailure("preparation_request_already_used")
            batch = session.scalar(select(KnowledgeIndexBatch).where(
                KnowledgeIndexBatch.index_id == index.id,
                KnowledgeIndexBatch.state == "pending").order_by(
                    KnowledgeIndexBatch.batch_number).with_for_update(skip_locked=True))
            if batch is None:
                return self._status(session, index)
            if idempotency_key is not None:
                batch.idempotency_key = idempotency_key
            manifest, chunks_by_id = self._load_chunks(session, owner, assistant, index)
            if manifest != index.manifest_sha256:
                index.state, index.error_code = "superseded", "source_manifest_changed"
                batch.state, batch.error_code = "failed", "source_manifest_changed"
                return self._status(session, index)
            selected = [chunks_by_id.get(chunk_id) for chunk_id in batch.chunk_ids]
            if any(c is None for c in selected):
                raise IndexingFailure("index_chunk_manifest_invalid")
            claim = uuid4()
            batch.state = "inflight"
            batch.operation_id = claim
            batch.attempts += 1
            batch.lease_expires_at = self.clock() + INDEX_LEASE
            index.operation_id = claim
            index.lease_expires_at = batch.lease_expires_at
            texts = tuple(c.text for c in selected)

        try:
            result = await self.provider.embed(texts)
            if (len(result.vectors) != len(selected) or result.dimensions != self.dimension
                    or result.model != self.embedding_model or result.total_tokens != result.prompt_tokens
                    or result.prompt_tokens > MAX_BATCH_TOKENS
                    or result.prompt_tokens > sum(len(self.tokenizer.encode(text)) for text in texts)):
                raise IndexingFailure("embedding_invalid_output")
            for vector in result.vectors:
                if (len(vector) != self.dimension
                        or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)
                        or math.hypot(*vector) == 0):
                    raise IndexingFailure("embedding_invalid_output")
        except EmbeddingFailure as exc:
            self._fail_batch(owner, assistant, index_id, claim, "embedding_provider_failure")
            raise IndexingFailure("embedding_provider_failure") from None
        except IndexingFailure:
            self._fail_batch(owner, assistant, index_id, claim, "embedding_invalid_output")
            raise

        with self.sessions.begin() as session:
            self._set_owner(session, owner)
            index = session.scalar(select(KnowledgeIndex).where(
                KnowledgeIndex.id == index_id, KnowledgeIndex.owner_id == owner,
                KnowledgeIndex.assistant_id == assistant).with_for_update())
            # Resolve batch by its fenced operation token (not by client-supplied ordinal).
            batch = session.scalar(select(KnowledgeIndexBatch).where(
                KnowledgeIndexBatch.index_id == index_id,
                KnowledgeIndexBatch.operation_id == claim,
                KnowledgeIndexBatch.state == "inflight").with_for_update())
            if (index is None or batch is None or index.operation_id != claim
                    or _as_utc(batch.lease_expires_at) <= _as_utc(self.clock())):
                raise IndexingFailure("index_operation_fenced")
            manifest, current = self._load_chunks(session, owner, assistant, index)
            if manifest != index.manifest_sha256:
                index.state = "superseded"
                index.error_code = "source_manifest_changed"
                batch.state = "uncertain"
                batch.error_code = "source_manifest_changed"
                batch.actual_tokens = result.total_tokens
                return self._status(session, index)
            selected = [current[cid] for cid in batch.chunk_ids]
            for chunk, vector in zip(selected, result.vectors):
                persisted_chunk_id = uuid5(
                    NAMESPACE_URL, f"assistant-builder:index:{index.id}:chunk:{chunk.id}")
                session.add(KnowledgeChunk(id=persisted_chunk_id, index_id=index.id, owner_id=owner,
                    assistant_id=assistant, file_id=chunk.file_id, ordinal=chunk.ordinal,
                    extraction_version=chunk.extraction_version, chunker_version=chunk.chunker_version,
                    source_sha256=chunk.source_sha256, start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset, token_count=chunk.token_count,
                    text_sha256=sha_text(chunk.text), chunk_text=chunk.text, embedding=vector))
            batch.state = "completed"
            batch.actual_tokens = result.total_tokens
            index.completed_chunks += len(selected)
            session.flush()
            pending = session.scalar(select(KnowledgeIndexBatch.id).where(
                KnowledgeIndexBatch.index_id == index.id,
                KnowledgeIndexBatch.state != "completed").limit(1))
            if pending is None:
                # Same transaction atomically publishes only a complete current manifest.
                assistant_row = session.scalar(select(Assistant).where(
                    Assistant.id == assistant, Assistant.owner_id == owner).with_for_update())
                current_manifest = self._sources(session, owner, assistant)[3]
                if current_manifest != index.manifest_sha256 or index.completed_chunks != index.total_chunks:
                    index.state, index.error_code = "superseded", "source_manifest_changed"
                    batch.state, batch.error_code = "uncertain", "source_manifest_changed"
                    return self._status(session, index)
                index.state, index.ready_at, index.error_code = "ready", self.clock(), None
                assistant_row.active_knowledge_index_id = index.id
            return self._status(session, index)

    def _fail_batch(self, owner, assistant, index_id, claim, code):
        with self.sessions.begin() as session:
            self._set_owner(session, owner)
            batch = session.scalar(select(KnowledgeIndexBatch).where(
                KnowledgeIndexBatch.index_id == index_id,
                KnowledgeIndexBatch.owner_id == owner, KnowledgeIndexBatch.assistant_id == assistant,
                KnowledgeIndexBatch.operation_id == claim,
                KnowledgeIndexBatch.state == "inflight").with_for_update())
            if batch:
                batch.state, batch.error_code = "failed", code
                index = session.scalar(select(KnowledgeIndex).where(KnowledgeIndex.id == index_id).with_for_update())
                if index:
                    index.state, index.error_code = "failed", code

    def recover_expired_batch(self, owner, assistant, index_id, batch_number, *, retry_approved=False):
        """Fence a late response. Retrying uncertain paid work requires explicit approval."""
        with self.sessions.begin() as session:
            self._set_owner(session, owner)
            index = session.scalar(select(KnowledgeIndex).where(KnowledgeIndex.id == index_id,
                KnowledgeIndex.owner_id == owner, KnowledgeIndex.assistant_id == assistant).with_for_update())
            batch = session.scalar(select(KnowledgeIndexBatch).where(
                KnowledgeIndexBatch.index_id == index_id, KnowledgeIndexBatch.owner_id == owner,
                KnowledgeIndexBatch.assistant_id == assistant,
                KnowledgeIndexBatch.batch_number == batch_number).with_for_update())
            if (index is None or batch is None or batch.state != "inflight"
                    or _as_utc(batch.lease_expires_at) > _as_utc(self.clock())):
                raise IndexingFailure("index_operation_not_expired")
            batch.operation_id = uuid4()
            batch.state = "pending" if retry_approved else "uncertain"
            batch.error_code = "provider_attempt_uncertain"
            if not retry_approved:
                index.state, index.error_code = "failed", "provider_attempt_uncertain"
            else:
                index.operation_id, index.state = uuid4(), "building"
                index.lease_expires_at = self.clock() + INDEX_LEASE
            return self._status(session, index)
