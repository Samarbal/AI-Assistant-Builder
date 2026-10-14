# شكل البيانات داخل قاعدة البيانات
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (DateTime, Index, JSON, String, Uuid, func, Text,
                        Integer, BigInteger, CheckConstraint, UniqueConstraint,
                        ForeignKeyConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Assistant(Base):
    __tablename__ = "assistants"
    __table_args__ = (Index("ix_assistants_owner_id", "owner_id"),
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
