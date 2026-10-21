"""Caller owns transactions and must set verified owner identity before queries.

No storage I/O, credentials, commits, physical deletion or recovery execution.
"""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Assistant, KnowledgeFile, KnowledgeFileText


class KnowledgeNotFound(Exception):
    pass


class KnowledgeLimitReached(Exception):
    pass


class KnowledgeStateConflict(Exception):
    pass


class KnowledgeRepository:
    def __init__(self, session: Session):
        self.session = session

    def _assistant(self, owner_id: UUID, assistant_id: UUID):
        row = self.session.scalar(select(Assistant).where(
            Assistant.owner_id == owner_id, Assistant.id == assistant_id
        ).with_for_update())
        if row is None:
            raise KnowledgeNotFound()
        return row

    def reserve(self, owner_id: UUID, assistant_id: UUID, *, filename: str,
                file_format: str, size_bytes: int, content_sha256: str,
                lease_expires_at: datetime) -> KnowledgeFile:
        if (file_format not in ('pdf', 'docx') or not 0 < size_bytes <= 10_000_000
                or not filename.strip() or len(filename) > 255
                or len(content_sha256) != 64
                or any(c not in '0123456789abcdef' for c in content_sha256)
                or lease_expires_at.tzinfo is None
                or lease_expires_at <= datetime.now(timezone.utc)):
            raise ValueError('Invalid reservation metadata')
        assistant = self._assistant(owner_id, assistant_id)
        # Any draft attachment change invalidates the old semantic corpus pointer.
        # The immutable index rows remain for recovery/inspection; they are not active.
        assistant.active_knowledge_index_id = None
        occupied = set(self.session.scalars(select(KnowledgeFile.slot_number).where(
            KnowledgeFile.owner_id == owner_id, KnowledgeFile.assistant_id == assistant_id,
            KnowledgeFile.removed_at.is_(None))))
        slot = next((n for n in range(1, 6) if n not in occupied), None)
        if slot is None:
            raise KnowledgeLimitReached()
        file_id = uuid4()
        item = KnowledgeFile(id=file_id, owner_id=owner_id, assistant_id=assistant_id,
            slot_number=slot, original_filename=filename, file_format=file_format,
            size_bytes=size_bytes, content_sha256=content_sha256,
            object_key=f'owners/{owner_id}/assistants/{assistant_id}/files/{file_id}/original.{file_format}',
            lease_expires_at=lease_expires_at, operation_id=uuid4())
        self.session.add(item)
        self.session.flush()
        return item

    def list_for_assistant(self, owner_id: UUID, assistant_id: UUID):
        return self.session.scalars(select(KnowledgeFile).where(
            KnowledgeFile.owner_id == owner_id, KnowledgeFile.assistant_id == assistant_id,
            KnowledgeFile.removed_at.is_(None)).order_by(KnowledgeFile.created_at, KnowledgeFile.id)).all()

    def get_for_owner(self, owner_id: UUID, assistant_id: UUID, file_id: UUID,
                      *, include_removed=False, lock=False):
        query = select(KnowledgeFile).where(KnowledgeFile.id == file_id,
            KnowledgeFile.owner_id == owner_id, KnowledgeFile.assistant_id == assistant_id)
        if not include_removed:
            query = query.where(KnowledgeFile.removed_at.is_(None))
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = self.session.scalar(query)
        if row is None:
            raise KnowledgeNotFound()
        return row

    def _operation(self, owner_id, assistant_id, file_id, operation_id, expected):
        row = self.get_for_owner(owner_id, assistant_id, file_id, lock=True)
        deadline = row.lease_expires_at
        # SQLite tests return naive timestamps; PostgreSQL uses timestamptz.
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if (row.operation_id != operation_id or row.processing_state not in expected
                or deadline <= datetime.now(timezone.utc)):
            raise KnowledgeStateConflict()
        return row

    def start_processing(self, owner_id, assistant_id, file_id, operation_id):
        row = self._operation(owner_id, assistant_id, file_id, operation_id, {'accepted'})
        row.processing_state = 'processing'
        self.session.flush()

    def complete_extraction(self, owner_id, assistant_id, file_id, operation_id,
                            *, extracted_text, extraction_version):
        if not extracted_text.strip() or not extraction_version or len(extraction_version) > 64:
            raise ValueError('Nonempty text and extraction version required')
        row = self._operation(owner_id, assistant_id, file_id, operation_id, {'processing'})
        assistant = self._assistant(owner_id, assistant_id)
        assistant.active_knowledge_index_id = None
        self.session.add(KnowledgeFileText(file_id=file_id, assistant_id=assistant_id,
            owner_id=owner_id, extracted_text=extracted_text, extraction_version=extraction_version))
        row.processing_state = 'extracted'
        row.error_code = None
        self.session.flush()

    def mark_failed(self, owner_id, assistant_id, file_id, operation_id, *, error_code):
        if error_code not in {'invalid_document', 'storage_unavailable', 'processing_failed', 'processing_timeout'}:
            raise ValueError('Use a safe error code, not exception details')
        row = self._operation(owner_id, assistant_id, file_id, operation_id, {'accepted', 'processing'})
        row.processing_state = 'failed'
        row.error_code = error_code
        row.cleanup_state = 'pending'
        self.session.flush()

    def remove(self, owner_id, assistant_id, file_id):
        assistant = self._assistant(owner_id, assistant_id)
        row = self.get_for_owner(owner_id, assistant_id, file_id, include_removed=True, lock=True)
        if row.removed_at is None:
            assistant.active_knowledge_index_id = None
            row.removed_at = datetime.now(timezone.utc)
            row.slot_number = None
            row.cleanup_state = 'pending'
            # Fence a late processor; preserve text and immutable artifact identity.
            row.operation_id = uuid4()
            self.session.flush()
        return row
