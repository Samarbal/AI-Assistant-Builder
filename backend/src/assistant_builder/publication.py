"""Owner-scoped immutable publication service. No HTTP/public chat routes here."""
from hashlib import sha256
import json
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .db import set_owner_identity
from .models import (Assistant, AssistantPublication, KnowledgeFile, KnowledgeFileText,
                     KnowledgeIndex, KnowledgeIndexSource, PublicationRequest,
                     PublishedSnapshot, PublishedSource)


class PublicationFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class PublicationService:
    """Creates a snapshot and changes the active pointer in the caller transaction."""

    def __init__(self, session: Session, *, embedding_provider: str,
                 embedding_model: str, vector_dimension: int = 768,
                 minimum_similarity: float | None = None):
        self.session = session
        self.embedding_provider = embedding_provider
        self.embedding_model = embedding_model
        self.vector_dimension = vector_dimension
        self.minimum_similarity = minimum_similarity

    def _draft(self, owner: UUID, assistant_id: UUID, *, lock: bool):
        query = select(Assistant).where(Assistant.id == assistant_id, Assistant.owner_id == owner)
        if lock:
            query = query.with_for_update()
        return self.session.scalar(query)

    def fingerprint(self, owner: UUID, assistant: Assistant) -> tuple[str, list[tuple[KnowledgeFile, KnowledgeFileText]]]:
        files = self.session.scalars(select(KnowledgeFile).where(
            KnowledgeFile.owner_id == owner, KnowledgeFile.assistant_id == assistant.id,
            KnowledgeFile.removed_at.is_(None)).order_by(KnowledgeFile.id)).all()
        if any(item.processing_state in {"accepted", "processing", "failed"} for item in files):
            raise PublicationFailure("knowledge_not_ready")
        rows = self.session.execute(select(KnowledgeFile, KnowledgeFileText).join(
            KnowledgeFileText, KnowledgeFileText.file_id == KnowledgeFile.id).where(
                KnowledgeFile.owner_id == owner, KnowledgeFile.assistant_id == assistant.id,
                KnowledgeFile.removed_at.is_(None), KnowledgeFile.processing_state == "extracted"
            ).order_by(KnowledgeFile.id)).all()
        if {f.id for f, _ in rows} != {f.id for f in files}:
            raise PublicationFailure("knowledge_not_ready")
        manifest_files = [{"file_id": str(file.id), "content_sha256": file.content_sha256,
                           "extraction_version": extracted.extraction_version,
                           "text_sha256": sha256(extracted.extracted_text.encode("utf-8")).hexdigest()}
                          for file, extracted in rows]
        manifest = _digest(manifest_files)
        active_index = None
        if rows:
            active_index = self.session.scalar(select(KnowledgeIndex).where(
                KnowledgeIndex.id == assistant.active_knowledge_index_id,
                KnowledgeIndex.owner_id == owner, KnowledgeIndex.assistant_id == assistant.id,
                KnowledgeIndex.state == "ready", KnowledgeIndex.ready_at.is_not(None),
                KnowledgeIndex.completed_chunks == KnowledgeIndex.total_chunks,
                KnowledgeIndex.manifest_sha256 == manifest,
                KnowledgeIndex.embedding_provider == self.embedding_provider,
                KnowledgeIndex.embedding_model == self.embedding_model,
                KnowledgeIndex.vector_dimension == self.vector_dimension).with_for_update())
            if active_index is None:
                raise PublicationFailure("knowledge_not_ready")
            indexed_sources = self.session.scalars(select(KnowledgeIndexSource).where(
                KnowledgeIndexSource.index_id == active_index.id,
                KnowledgeIndexSource.owner_id == owner,
                KnowledgeIndexSource.assistant_id == assistant.id).order_by(KnowledgeIndexSource.file_id)).all()
            if len(indexed_sources) != len(rows) or any(
                    src.file_id != file.id or src.extraction_version != extracted.extraction_version or
                    src.source_sha256 != sha256(extracted.extracted_text.encode("utf-8")).hexdigest()
                    for src, (file, extracted) in zip(indexed_sources, rows)):
                raise PublicationFailure("knowledge_not_ready")
        config = {"name": assistant.name, "role": assistant.role, "colors": assistant.colors,
                  "response_style": assistant.response_style, "tone": assistant.tone,
                  "fallback_message": assistant.fallback_message}
        return _digest({"config": config, "manifest": manifest,
                        "index_id": str(active_index.id) if active_index else None,
                        "embedding_provider": self.embedding_provider if active_index else None,
                        "embedding_model": self.embedding_model if active_index else None,
                        "vector_dimension": self.vector_dimension if active_index else None,
                        "minimum_similarity": self.minimum_similarity}), rows, manifest

    def status(self, owner: UUID, assistant_id: UUID) -> dict:
        """Return owner-visible publication state and a current-draft concurrency token."""
        if not isinstance(owner, UUID) or not isinstance(assistant_id, UUID):
            raise PublicationFailure("invalid_request")
        assistant = self._draft(owner, assistant_id, lock=False)
        if assistant is None:
            raise PublicationFailure("not_found")
        publication = self.session.scalar(select(AssistantPublication).where(
            AssistantPublication.owner_id == owner,
            AssistantPublication.assistant_id == assistant_id))
        snapshot = self.session.scalar(select(PublishedSnapshot).where(
            PublishedSnapshot.id == publication.active_snapshot_id,
            PublishedSnapshot.owner_id == owner,
            PublishedSnapshot.assistant_id == assistant_id)) if publication and publication.active_snapshot_id else None
        files = self.session.scalars(select(KnowledgeFile).where(
            KnowledgeFile.owner_id == owner, KnowledgeFile.assistant_id == assistant_id,
            KnowledgeFile.removed_at.is_(None)).order_by(KnowledgeFile.id)).all()

        if not files:
            fingerprint, _, _ = self.fingerprint(owner, assistant)
            readiness = "fallback_only"
        else:
            states = {item.processing_state for item in files}
            if states & {"accepted", "processing"}:
                readiness = "processing"
            elif "failed" in states or states - {"extracted"}:
                readiness = "failed"
            else:
                try:
                    fingerprint, _, _ = self.fingerprint(owner, assistant)
                    readiness = "ready"
                except PublicationFailure as exc:
                    if exc.code != "knowledge_not_ready":
                        raise
                    readiness = "needs_preparation"
            if readiness != "ready":
                extracted = {row.file_id: row for row in self.session.scalars(
                    select(KnowledgeFileText).where(
                        KnowledgeFileText.owner_id == owner,
                        KnowledgeFileText.assistant_id == assistant_id)).all()}
                manifest_files = [{
                    "file_id": str(item.id),
                    "content_sha256": item.content_sha256,
                    "processing_state": item.processing_state,
                    "extraction_version": extracted[item.id].extraction_version if item.id in extracted else None,
                    "text_sha256": sha256(extracted[item.id].extracted_text.encode("utf-8")).hexdigest()
                        if item.id in extracted else None,
                } for item in files]
                config = {"name": assistant.name, "role": assistant.role, "colors": assistant.colors,
                          "response_style": assistant.response_style, "tone": assistant.tone,
                          "fallback_message": assistant.fallback_message}
                fingerprint = _digest({"config": config, "files": manifest_files,
                                       "active_index_id": str(assistant.active_knowledge_index_id)
                                           if assistant.active_knowledge_index_id else None})

        return {
            "published": snapshot is not None,
            "public_id": publication.public_id if publication else None,
            "version": snapshot.version if snapshot else None,
            "published_at": snapshot.activated_at if snapshot else None,
            "draft_fingerprint": fingerprint,
            "has_changes": snapshot is None or snapshot.draft_fingerprint != fingerprint,
            "readiness": readiness,
        }

    def get_active_publication(self, owner: UUID, assistant_id: UUID) -> AssistantPublication:
        if not isinstance(owner, UUID) or not isinstance(assistant_id, UUID):
            raise PublicationFailure("invalid_request")
        if self._draft(owner, assistant_id, lock=False) is None:
            raise PublicationFailure("not_found")
        publication = self.session.scalar(select(AssistantPublication).where(
            AssistantPublication.owner_id == owner,
            AssistantPublication.assistant_id == assistant_id))
        if publication is None or publication.active_snapshot_id is None:
            raise PublicationFailure("not_published")
        snapshot = self.session.scalar(select(PublishedSnapshot).where(
            PublishedSnapshot.id == publication.active_snapshot_id,
            PublishedSnapshot.owner_id == owner,
            PublishedSnapshot.assistant_id == assistant_id,
            PublishedSnapshot.state == "published"))
        if snapshot is None:
            raise PublicationFailure("publication_unavailable")
        return publication

    def publish(self, owner: UUID, assistant_id: UUID, *, expected_fingerprint: str,
                expected_version: int | None, idempotency_key: str) -> tuple[AssistantPublication, PublishedSnapshot, bool]:
        if not isinstance(owner, UUID) or not isinstance(assistant_id, UUID):
            raise PublicationFailure("invalid_request")
        if not idempotency_key or len(idempotency_key) > 128 or not idempotency_key.isascii():
            raise PublicationFailure("invalid_request")
        if not isinstance(expected_fingerprint, str) or len(expected_fingerprint) != 64:
            raise PublicationFailure("invalid_request")
        if self.session.bind.dialect.name == "postgresql":
            set_owner_identity(self.session, owner)
        # Check existence before acquiring the per-assistant transaction lock.
        if self._draft(owner, assistant_id, lock=False) is None:
            raise PublicationFailure("not_found")
        request_hash = _digest({"expected_fingerprint": expected_fingerprint,
                                "expected_version": expected_version})
        previous = self.session.scalar(select(PublicationRequest).where(
            PublicationRequest.owner_id == owner, PublicationRequest.assistant_id == assistant_id,
            PublicationRequest.idempotency_key == idempotency_key))
        if previous is not None:
            if previous.request_sha256 != request_hash:
                raise PublicationFailure("idempotency_conflict")
            publication = self.session.scalar(select(AssistantPublication).where(
                AssistantPublication.owner_id == owner, AssistantPublication.assistant_id == assistant_id))
            snapshot = self.session.get(PublishedSnapshot, previous.snapshot_id)
            if publication is None or snapshot is None:
                raise PublicationFailure("publication_unavailable")
            return publication, snapshot, True
        if self.session.bind.dialect.name == "postgresql":
            lock_key = f"publish:{assistant_id}"
            self.session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": lock_key})
        assistant = self._draft(owner, assistant_id, lock=True)
        if assistant is None:
            raise PublicationFailure("not_found")
        # A parallel request with the same key may have committed while this request
        # waited for the advisory lock. Replay only after validating its request hash.
        previous = self.session.scalar(select(PublicationRequest).where(
            PublicationRequest.owner_id == owner, PublicationRequest.assistant_id == assistant_id,
            PublicationRequest.idempotency_key == idempotency_key))
        if previous is not None:
            if previous.request_sha256 != request_hash:
                raise PublicationFailure("idempotency_conflict")
            publication = self.session.scalar(select(AssistantPublication).where(
                AssistantPublication.owner_id == owner, AssistantPublication.assistant_id == assistant_id))
            snapshot = self.session.get(PublishedSnapshot, previous.snapshot_id)
            if publication is None or snapshot is None:
                raise PublicationFailure("publication_unavailable")
            return publication, snapshot, True
        fingerprint, rows, index_manifest = self.fingerprint(owner, assistant)
        if fingerprint != expected_fingerprint:
            raise PublicationFailure("draft_changed")
        publication = self.session.scalar(select(AssistantPublication).where(
            AssistantPublication.owner_id == owner, AssistantPublication.assistant_id == assistant_id).with_for_update())
        old_snapshot = None
        if publication is None:
            if expected_version is not None:
                raise PublicationFailure("publication_changed")
            publication = AssistantPublication(id=uuid4(), public_id=uuid4(),
                assistant_id=assistant.id, owner_id=owner, active_snapshot_id=None)
            self.session.add(publication)
            self.session.flush()
            next_version = 1
        else:
            old_snapshot = self.session.scalar(select(PublishedSnapshot).where(
                PublishedSnapshot.id == publication.active_snapshot_id,
                PublishedSnapshot.assistant_id == assistant.id,
                PublishedSnapshot.owner_id == owner)) if publication.active_snapshot_id else None
            current_version = old_snapshot.version if old_snapshot else None
            if current_version != expected_version:
                raise PublicationFailure("publication_changed")
            if old_snapshot and old_snapshot.draft_fingerprint == fingerprint:
                # Fingerprint also covers config and retrieval identity; same content
                # is already active, so persist this idempotency result without a version.
                request = PublicationRequest(id=uuid4(), assistant_id=assistant.id, owner_id=owner,
                    idempotency_key=idempotency_key, request_sha256=request_hash, snapshot_id=old_snapshot.id)
                self.session.add(request)
                self.session.flush()
                return publication, old_snapshot, True
            next_version = (self.session.scalar(select(func.max(PublishedSnapshot.version)).where(
                PublishedSnapshot.owner_id == owner, PublishedSnapshot.assistant_id == assistant.id)) or 0) + 1

        active_index = assistant.active_knowledge_index_id if rows else None
        index = self.session.get(KnowledgeIndex, active_index) if active_index else None
        manifest_hash = index_manifest
        snapshot = PublishedSnapshot(id=uuid4(), assistant_id=assistant.id, owner_id=owner,
            version=next_version, state="published",
            config={"name": assistant.name, "role": assistant.role, "colors": assistant.colors,
                    "response_style": assistant.response_style, "tone": assistant.tone,
                    "fallback_message": assistant.fallback_message},
            draft_fingerprint=fingerprint,
            knowledge_index_id=active_index,
            embedding_provider=index.embedding_provider if index else None,
            embedding_model=index.embedding_model if index else None,
            vector_dimension=index.vector_dimension if index else None,
            retrieval_min_similarity=self.minimum_similarity if index else None,
            manifest_sha256=manifest_hash, source_count=len(rows), activated_at=func.now())
        self.session.add(snapshot)
        self.session.flush()
        for file, extracted in rows:
            self.session.add(PublishedSource(snapshot_id=snapshot.id, file_id=file.id,
                assistant_id=assistant.id, owner_id=owner, index_id=active_index,
                source_sha256=sha256(extracted.extracted_text.encode("utf-8")).hexdigest(),
                extraction_version=extracted.extraction_version))
        self.session.flush()
        publication.active_snapshot_id = snapshot.id
        publication.updated_at = func.now()
        request = PublicationRequest(id=uuid4(), assistant_id=assistant.id, owner_id=owner,
            idempotency_key=idempotency_key, request_sha256=request_hash, snapshot_id=snapshot.id)
        self.session.add(request)
        self.session.flush()
        return publication, snapshot, False
