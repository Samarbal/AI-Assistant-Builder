"""Short owner-scoped transactions around slow, external ingestion work."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from .db import set_owner_identity
from .extraction import InvalidDocument, extract_text
from .knowledge_repository import KnowledgeRepository
from .storage import StorageUnavailable


class KnowledgeNotReady(Exception):
    pass


class KnowledgeService:
    def __init__(self, session_factory, storage, extractor=extract_text):
        self.sessions = session_factory
        self.storage = storage
        self.extractor = extractor

    @contextmanager
    def transaction(self, owner):
        with self.sessions.begin() as session:
            set_owner_identity(session, owner)
            yield KnowledgeRepository(session)

    def upload(self, owner, assistant, filename, content):
        with self.transaction(owner) as repo:
            item = repo.reserve(owner, assistant, filename=filename,
                file_format=filename.rsplit('.', 1)[-1].lower(), size_bytes=len(content),
                content_sha256=sha256(content).hexdigest(),
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
            file_id, operation, key, file_format = item.id, item.operation_id, item.object_key, item.file_format
            repo.start_processing(owner, assistant, file_id, operation)
        try:
            extracted = self.extractor(content, file_format)
            self.storage.upload(key, content, file_format)
            with self.transaction(owner) as repo:
                repo.complete_extraction(owner, assistant, file_id, operation,
                    extracted_text=extracted, extraction_version='pdf-docx-v1')
                result = repo.get_for_owner(owner, assistant, file_id)
            return result
        except (InvalidDocument, StorageUnavailable) as exc:
            code = 'invalid_document' if isinstance(exc, InvalidDocument) else 'storage_unavailable'
            with self.transaction(owner) as repo:
                repo.mark_failed(owner, assistant, file_id, operation, error_code=code)
            raise
        # An uncertain database commit is deliberately not compensated by deleting
        # an object. The durable reservation/key permits operator recovery.

    def list(self, owner, assistant):
        with self.transaction(owner) as repo:
            repo._assistant(owner, assistant)
            return repo.list_for_assistant(owner, assistant)

    def remove(self, owner, assistant, file_id):
        with self.transaction(owner) as repo:
            repo.remove(owner, assistant, file_id)

    def download_url(self, owner, assistant, file_id, expires_in):
        with self.transaction(owner) as repo:
            item = repo.get_for_owner(owner, assistant, file_id)
            if item.processing_state != 'extracted':
                raise KnowledgeNotReady()
            key, filename = item.object_key, item.original_filename
        if self.storage is None:
            raise StorageUnavailable()
        url = self.storage.signed_download_url(key, filename, expires_in)
        # Do not deliver a URL if removal occurred while Storage was signing it.
        with self.transaction(owner) as repo:
            repo.get_for_owner(owner, assistant, file_id)
        return url
