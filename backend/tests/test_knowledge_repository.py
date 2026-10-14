from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from assistant_builder.models import Base, Assistant, KnowledgeFileText
from assistant_builder.knowledge_repository import (
    KnowledgeRepository, KnowledgeLimitReached, KnowledgeNotFound, KnowledgeStateConflict,
)
from .test_phase1_contracts import payload


def reserve(repo, owner, assistant):
    return repo.reserve(owner, assistant, filename='faq.pdf', file_format='pdf',
        size_bytes=100, content_sha256='a' * 64,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))


@pytest.fixture
def knowledge():
    engine = create_engine('sqlite://')
    event.listen(engine, 'connect', lambda connection, _: connection.execute('PRAGMA foreign_keys=ON'))
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False).begin() as session:
        owner, other = uuid4(), uuid4()
        assistant = Assistant(owner_id=owner, **payload())
        session.add(assistant)
        session.flush()
        yield session, KnowledgeRepository(session), owner, other, assistant.id
    engine.dispose()


def test_five_slots_failed_files_count_removal_releases_slot(knowledge):
    session, repo, owner, _, assistant = knowledge
    files = [reserve(repo, owner, assistant) for _ in range(5)]
    repo.mark_failed(owner, assistant, files[0].id, files[0].operation_id, error_code='invalid_document')
    with pytest.raises(KnowledgeLimitReached):
        reserve(repo, owner, assistant)
    repo.remove(owner, assistant, files[0].id)
    repo.remove(owner, assistant, files[0].id)  # idempotent
    replacement = reserve(repo, owner, assistant)
    assert replacement.slot_number == 1 and replacement.id != files[0].id
    assert len(repo.list_for_assistant(owner, assistant)) == 5


def test_owner_and_parent_scoping(knowledge):
    _, repo, owner, other, assistant = knowledge
    item = reserve(repo, owner, assistant)
    assert repo.list_for_assistant(other, assistant) == []
    for requested_owner, parent in ((other, assistant), (owner, uuid4())):
        with pytest.raises(KnowledgeNotFound):
            repo.get_for_owner(requested_owner, parent, item.id)
        with pytest.raises(KnowledgeNotFound):
            repo.remove(requested_owner, parent, item.id)
    with pytest.raises(KnowledgeNotFound):
        reserve(repo, other, assistant)


def test_text_persists_and_removal_preserves_artifact(knowledge):
    session, repo, owner, _, assistant = knowledge
    item = reserve(repo, owner, assistant)
    repo.start_processing(owner, assistant, item.id, item.operation_id)
    repo.complete_extraction(owner, assistant, item.id, item.operation_id,
        extracted_text='Business knowledge', extraction_version='test-v1')
    assert item.processing_state == 'extracted'
    repo.remove(owner, assistant, item.id)
    assert session.scalar(select(KnowledgeFileText.extracted_text)) == 'Business knowledge'
    assert item.cleanup_state == 'pending'


def test_stale_operation_and_removed_file_cannot_finalize(knowledge):
    session, repo, owner, _, assistant = knowledge
    item = reserve(repo, owner, assistant)
    with pytest.raises(KnowledgeStateConflict):
        repo.start_processing(owner, assistant, item.id, uuid4())
    op = item.operation_id
    repo.start_processing(owner, assistant, item.id, op)
    repo.remove(owner, assistant, item.id)
    with pytest.raises(KnowledgeNotFound):
        repo.complete_extraction(owner, assistant, item.id, op,
            extracted_text='late', extraction_version='v1')
    assert session.scalar(select(KnowledgeFileText.file_id)) is None


def test_expired_operation_is_rejected(knowledge):
    _, repo, owner, _, assistant = knowledge
    item = reserve(repo, owner, assistant)
    item.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    repo.session.flush()
    with pytest.raises(KnowledgeStateConflict):
        repo.start_processing(owner, assistant, item.id, item.operation_id)
