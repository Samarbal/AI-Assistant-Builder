# شكل البيانات داخل قاعدة البيانات
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (DateTime, Index, JSON, String, Uuid, func, Text,
                        Integer, BigInteger, CheckConstraint, UniqueConstraint,
                        ForeignKeyConstraint, ForeignKey)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType
from sqlalchemy.ext.compiler import compiles


class Vector768(UserDefinedType):
    """pgvector binding without an extra ORM package dependency."""
    cache_ok = True

    def get_col_spec(self, **kw):
        return "public.vector(768)"

    def bind_processor(self, dialect):
        def bind(value):
            if value is None:
                return None
            if (not isinstance(value, (tuple, list)) or len(value) != 768
                    or any(type(number) not in (int, float) for number in value)):
                raise ValueError("Expected a 768-dimensional vector")
            import math
            if any(not math.isfinite(number) for number in value):
                raise ValueError("Vector values must be finite")
            return "[" + ",".join(repr(float(number)) for number in value) + "]"
        return bind

    def result_processor(self, dialect, coltype):
        def result(value):
            if value is None:
                return None
            if not isinstance(value, str) or not value.startswith("[") or not value.endswith("]"):
                raise ValueError("Malformed pgvector value")
            import math
            vector = tuple(float(part) for part in value[1:-1].split(","))
            if len(vector) != 768 or any(not math.isfinite(v) for v in vector):
                raise ValueError("Malformed pgvector dimensions or values")
            return vector
        return result


@compiles(Vector768, "sqlite")
def _compile_vector768_for_sqlite(type_, compiler, **kw):
    # SQLite is used only by isolated unit tests; production uses public.vector.
    return "vector(768)"


class Base(DeclarativeBase):
    pass


class Assistant(Base):
    __tablename__ = "assistants"
    __table_args__ = (ForeignKeyConstraint(
                          ["active_knowledge_index_id", "id", "owner_id"],
                          ["knowledge_indexes.id", "knowledge_indexes.assistant_id",
                           "knowledge_indexes.owner_id"],
                          name="fk_assistant_active_index"),
                      Index("ix_assistants_owner_id", "owner_id"),
                      UniqueConstraint("id", "owner_id", name="uq_assistants_id_owner"))

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(500), nullable=False)
    colors: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    response_style: Mapped[str] = mapped_column(String(100), nullable=False)
    tone: Mapped[str] = mapped_column(String(100), nullable=False)
    fallback_message: Mapped[str] = mapped_column(String(500), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    active_knowledge_index_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class KnowledgeFile(Base):
    __tablename__ = "knowledge_files"
    __table_args__ = (
        ForeignKeyConstraint(["assistant_id", "owner_id"], ["assistants.id", "assistants.owner_id"], name="fk_knowledge_assistant_owner"),
        UniqueConstraint("id", "assistant_id", "owner_id", name="uq_knowledge_identity"),
        UniqueConstraint("assistant_id", "slot_number", name="uq_knowledge_slot"),
        UniqueConstraint("object_key", name="uq_knowledge_object_key"),
        CheckConstraint("slot_number IS NULL OR slot_number BETWEEN 1 AND 5", name="ck_knowledge_slot"),
        CheckConstraint("(removed_at IS NULL AND slot_number IS NOT NULL) OR (removed_at IS NOT NULL AND slot_number IS NULL)", name="ck_knowledge_attachment"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 10000000", name="ck_knowledge_size"),
        CheckConstraint("file_format IN ('pdf', 'docx')", name="ck_knowledge_format"),
        CheckConstraint("processing_state IN ('accepted', 'processing', 'extracted', 'failed')", name="ck_knowledge_state"),
        CheckConstraint("cleanup_state IN ('not_needed', 'pending', 'complete')", name="ck_knowledge_cleanup"),
        CheckConstraint("cleanup_attempts >= 0", name="ck_knowledge_cleanup_attempts"),
        CheckConstraint("length(content_sha256) = 64", name="ck_knowledge_hash"),
        Index("ix_knowledge_owner_assistant", "owner_id", "assistant_id"),
        Index("ix_knowledge_recovery", "processing_state", "lease_expires_at"),
        Index("ix_knowledge_cleanup", "cleanup_state", "updated_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    slot_number: Mapped[int | None] = mapped_column(Integer)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(4), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    processing_state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="accepted")
    error_code: Mapped[str | None] = mapped_column(String(64))
    operation_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False, default=uuid4)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleanup_state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="not_needed")
    cleanup_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cleanup_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class KnowledgeFileText(Base):
    __tablename__ = "knowledge_file_text"
    __table_args__ = (
        ForeignKeyConstraint(["file_id", "assistant_id", "owner_id"], ["knowledge_files.id", "knowledge_files.assistant_id", "knowledge_files.owner_id"], name="fk_knowledge_text_owner"),
        CheckConstraint("length(extracted_text) > 0", name="ck_knowledge_text_nonempty"),
        Index("ix_knowledge_text_owner_assistant", "owner_id", "assistant_id"),
    )
    file_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    assistant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class KnowledgeIndex(Base):
    __tablename__ = "knowledge_indexes"
    __table_args__ = (
        ForeignKeyConstraint(["assistant_id", "owner_id"], ["assistants.id", "assistants.owner_id"], name="fk_index_assistant_owner"),
        UniqueConstraint("id", "assistant_id", "owner_id", name="uq_index_identity"),
        UniqueConstraint("assistant_id", "owner_id", "version", name="uq_index_version"),
        UniqueConstraint("assistant_id", "owner_id", "idempotency_key", name="uq_index_request"),
        CheckConstraint("version > 0", name="ck_index_version"),
        CheckConstraint("state IN ('building', 'ready', 'failed', 'superseded')", name="ck_index_state"),
        CheckConstraint("vector_dimension = 768", name="ck_index_dimension"),
        CheckConstraint("total_chunks BETWEEN 1 AND 200", name="ck_index_total_chunks"),
        CheckConstraint("completed_chunks BETWEEN 0 AND total_chunks", name="ck_index_completed_chunks"),
        CheckConstraint("(state = 'ready' AND ready_at IS NOT NULL AND completed_chunks = total_chunks) OR (state <> 'ready' AND ready_at IS NULL)", name="ck_index_ready_complete"),
        CheckConstraint("length(manifest_sha256) = 64", name="ck_index_manifest_hash"),
        Index("ix_index_owner_assistant_state", "owner_id", "assistant_id", "state"),
        Index("uq_index_one_building", "assistant_id", unique=True,
              postgresql_where=(__import__("sqlalchemy").text("state = 'building'"))),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    vector_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    tokenizer_version: Mapped[str] = mapped_column(String(128), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(256), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="building")
    operation_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False, default=uuid4)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    reserved_cost_microusd: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeIndexSource(Base):
    __tablename__ = "knowledge_index_sources"
    __table_args__ = (
        ForeignKeyConstraint(["index_id", "assistant_id", "owner_id"], ["knowledge_indexes.id", "knowledge_indexes.assistant_id", "knowledge_indexes.owner_id"], name="fk_index_source_index"),
        ForeignKeyConstraint(["file_id", "assistant_id", "owner_id"], ["knowledge_files.id", "knowledge_files.assistant_id", "knowledge_files.owner_id"], name="fk_index_source_file"),
        UniqueConstraint("index_id", "file_id", "assistant_id", "owner_id", name="uq_index_source_identity"),
        CheckConstraint("length(source_sha256) = 64", name="ck_index_source_hash"),
        Index("ix_index_source_owner_assistant", "owner_id", "assistant_id", "file_id"),
    )
    index_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    file_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    assistant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class KnowledgeIndexBatch(Base):
    __tablename__ = "knowledge_index_batches"
    __table_args__ = (
        ForeignKeyConstraint(["index_id", "assistant_id", "owner_id"], ["knowledge_indexes.id", "knowledge_indexes.assistant_id", "knowledge_indexes.owner_id"], name="fk_index_batch_index"),
        UniqueConstraint("index_id", "batch_number", name="uq_index_batch_number"),
        UniqueConstraint("index_id", "idempotency_key", name="uq_index_batch_idempotency"),
        CheckConstraint("batch_number >= 0", name="ck_index_batch_number"),
        CheckConstraint("state IN ('pending', 'inflight', 'completed', 'uncertain', 'failed')", name="ck_index_batch_state"),
        CheckConstraint("reserved_tokens BETWEEN 1 AND 4800", name="ck_index_batch_tokens"),
        CheckConstraint("attempts >= 0", name="ck_index_batch_attempts"),
        Index("ix_index_batch_recovery", "state", "lease_expires_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True, default=uuid4)
    index_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    batch_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid(), nullable=False, default=uuid4)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reserved_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_cost_microusd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    operation_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False, default=uuid4)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    actual_tokens: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        ForeignKeyConstraint(["index_id", "assistant_id", "owner_id"], ["knowledge_indexes.id", "knowledge_indexes.assistant_id", "knowledge_indexes.owner_id"], name="fk_chunk_index"),
        ForeignKeyConstraint(["index_id", "file_id", "assistant_id", "owner_id"], ["knowledge_index_sources.index_id", "knowledge_index_sources.file_id", "knowledge_index_sources.assistant_id", "knowledge_index_sources.owner_id"], name="fk_chunk_source"),
        UniqueConstraint("index_id", "file_id", "ordinal", name="uq_chunk_source_ordinal"),
        CheckConstraint("ordinal >= 0 AND start_offset >= 0 AND end_offset > start_offset", name="ck_chunk_offsets"),
        CheckConstraint("token_count BETWEEN 1 AND 600", name="ck_chunk_tokens"),
        CheckConstraint("length(text_sha256) = 64", name="ck_chunk_hash"),
        Index("ix_chunk_owner_assistant_index", "owner_id", "assistant_id", "index_id"),
        Index("ix_chunk_file_order", "index_id", "file_id", "ordinal"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    index_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    file_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(64), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(256), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[tuple[float, ...]] = mapped_column(Vector768(), nullable=False)


class AssistantPublication(Base):
    """Stable public handle and active immutable snapshot pointer."""
    __tablename__ = "assistant_publications"
    __table_args__ = (
        ForeignKeyConstraint(["assistant_id", "owner_id"], ["assistants.id", "assistants.owner_id"], name="fk_publication_assistant_owner"),
        UniqueConstraint("public_id"), UniqueConstraint("assistant_id", "owner_id"),
        ForeignKeyConstraint(["active_snapshot_id", "assistant_id", "owner_id"],
            ["published_snapshots.id", "published_snapshots.assistant_id", "published_snapshots.owner_id"],
            name="fk_publication_active_snapshot", use_alter=True),
        Index("ix_publication_owner_assistant", "owner_id", "assistant_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True, default=uuid4)
    public_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False, default=uuid4)
    assistant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    active_snapshot_id: Mapped[UUID | None] = mapped_column(Uuid())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PublishedSnapshot(Base):
    __tablename__ = "published_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(["assistant_id", "owner_id"], ["assistants.id", "assistants.owner_id"], name="fk_snapshot_assistant_owner"),
        UniqueConstraint("id", "assistant_id", "owner_id"),
        UniqueConstraint("assistant_id", "owner_id", "version"),
        CheckConstraint("version > 0", name="ck_snapshot_version"),
        CheckConstraint("state = 'published'", name="ck_snapshot_state"),
        CheckConstraint("(knowledge_index_id IS NULL) = (source_count = 0)", name="ck_snapshot_empty_manifest"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True, default=uuid4)
    assistant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(12), nullable=False, server_default="published")
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    draft_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    knowledge_index_id: Mapped[UUID | None] = mapped_column(Uuid())
    embedding_provider: Mapped[str | None] = mapped_column(String(32))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    vector_dimension: Mapped[int | None] = mapped_column(Integer)
    retrieval_min_similarity: Mapped[float | None] = mapped_column()
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    build_xid: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=func.txid_current())


class PublishedSource(Base):
    __tablename__ = "published_sources"
    __table_args__ = (
        ForeignKeyConstraint(["snapshot_id", "assistant_id", "owner_id"], ["published_snapshots.id", "published_snapshots.assistant_id", "published_snapshots.owner_id"], name="fk_published_source_snapshot"),
        ForeignKeyConstraint(["index_id", "assistant_id", "owner_id"], ["knowledge_indexes.id", "knowledge_indexes.assistant_id", "knowledge_indexes.owner_id"], name="fk_published_source_index"),
        ForeignKeyConstraint(["index_id", "file_id", "assistant_id", "owner_id"], ["knowledge_index_sources.index_id", "knowledge_index_sources.file_id", "knowledge_index_sources.assistant_id", "knowledge_index_sources.owner_id"], name="fk_published_source_index_file"),
        UniqueConstraint("snapshot_id", "file_id"),
    )
    snapshot_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    file_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    assistant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    index_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PublicationRequest(Base):
    __tablename__ = "publication_requests"
    __table_args__ = (ForeignKeyConstraint(["assistant_id", "owner_id"], ["assistants.id", "assistants.owner_id"]),)
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True, default=uuid4)
    assistant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class VisitorConversation(Base):
    __tablename__ = "visitor_conversations"
    __table_args__ = (
        ForeignKeyConstraint(["assistant_id", "owner_id"], ["assistants.id", "assistants.owner_id"]),
        ForeignKeyConstraint(["publication_id", "assistant_id", "owner_id"], ["assistant_publications.id", "assistant_publications.assistant_id", "assistant_publications.owner_id"]),
        UniqueConstraint("id", "publication_id", "owner_id", "assistant_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True, default=uuid4)
    publication_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class VisitorTurn(Base):
    __tablename__ = "visitor_turns"
    __table_args__ = (
        ForeignKeyConstraint(["conversation_id", "publication_id", "owner_id", "assistant_id"], ["visitor_conversations.id", "visitor_conversations.publication_id", "visitor_conversations.owner_id", "visitor_conversations.assistant_id"]),
        ForeignKeyConstraint(["snapshot_id", "assistant_id", "owner_id"], ["published_snapshots.id", "published_snapshots.assistant_id", "published_snapshots.owner_id"]),
        UniqueConstraint("conversation_id", "request_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    publication_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    snapshot_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    request_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    user_text: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    answer_text: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
