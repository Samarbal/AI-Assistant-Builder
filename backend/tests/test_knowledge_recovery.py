from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
import json

import httpx
import pytest
from sqlalchemy import select

from assistant_builder.knowledge_recovery import KnowledgeRecovery, RecoveryBlocked
from assistant_builder.knowledge_repository import KnowledgeRepository, KnowledgeNotFound, KnowledgeStateConflict
from assistant_builder.models import KnowledgeFile, KnowledgeFileText
from assistant_builder.storage import SupabaseFileStorage, StorageUnavailable
from .test_knowledge_upload import workflow, docx_bytes


@pytest.fixture
def recovery(workflow, monkeypatch):
    flow, owner, assistant, sessions, _ = workflow
    monkeypatch.setattr('assistant_builder.knowledge_recovery.set_owner_identity', lambda session, owner: None)
    clock = [datetime.now(timezone.utc)]
    deleted = []
    store = SimpleNamespace(remove_recorded_object=lambda key: deleted.append(key))
    tool = KnowledgeRecovery(sessions, store, guard=lambda session: None, clock=lambda: clock[0])
    item = flow.upload(owner, assistant, 'test.docx', docx_bytes())
    return tool, flow, owner, assistant, sessions, item, deleted, clock


def removed(recovery):
    tool, flow, owner, assistant, sessions, item, deleted, clock = recovery
    flow.remove(owner, assistant, item.id)
    clock[0] += timedelta(minutes=20)
    with sessions() as session:
        operation = session.get(KnowledgeFile, item.id).operation_id
    return operation


def test_dry_run_never_updates_or_calls_storage(recovery):
    tool, _, owner, assistant, sessions, item, deleted, _ = recovery
    operation = removed(recovery)
    assert tool.preview(owner, assistant) == [{'file_id': str(item.id), 'operation_id': str(operation),
        'action': 'delete_recorded_original', 'cleanup_attempts': 0}]
    with sessions() as session:
        assert session.get(KnowledgeFile, item.id).operation_id == operation
        assert session.get(KnowledgeFile, item.id).cleanup_attempts == 0
    assert not deleted


def test_success_preserves_metadata_and_text_and_is_repeatable(recovery):
    tool, _, owner, assistant, sessions, item, deleted, _ = recovery
    operation = removed(recovery)
    assert tool.apply(owner, assistant, item.id, operation, writers_stopped=True) == 'cleanup_complete'
    with sessions() as session:
        row = session.get(KnowledgeFile, item.id)
        assert row.cleanup_state == 'complete' and row.cleanup_attempts == 1
        assert session.get(KnowledgeFileText, item.id) is not None
        current = row.operation_id
    assert tool.apply(owner, assistant, item.id, current, writers_stopped=True) == 'already_complete'
    assert deleted == [item.object_key]


def test_no_apply_without_maintenance_window(recovery):
    tool, _, owner, assistant, _, item, deleted, _ = recovery
    operation = removed(recovery)
    with pytest.raises(RecoveryBlocked):
        tool.apply(owner, assistant, item.id, operation)
    assert not deleted


def test_active_lease_or_recent_removal_waits(recovery):
    tool, flow, owner, assistant, sessions, item, deleted, _ = recovery
    flow.remove(owner, assistant, item.id)
    with sessions() as session:
        op = session.get(KnowledgeFile, item.id).operation_id
    assert tool.apply(owner, assistant, item.id, op, writers_stopped=True) == 'wait_for_quiet_period'
    assert not deleted


def test_expired_operation_fenced_without_detaching_or_deleting(recovery):
    tool, _, owner, assistant, sessions, item, deleted, clock = recovery
    with sessions.begin() as session:
        row = session.get(KnowledgeFile, item.id)
        row.processing_state = 'processing'
        old = row.operation_id
    clock[0] += timedelta(minutes=20)
    assert tool.apply(owner, assistant, item.id, old, writers_stopped=True) == 'mark_expired_failed'
    with sessions() as session:
        row = session.get(KnowledgeFile, item.id)
        assert row.removed_at is None and row.slot_number == 1 and row.processing_state == 'failed'
        assert row.operation_id != old
        with pytest.raises(KnowledgeStateConflict):
            KnowledgeRepository(session).complete_extraction(owner, assistant, item.id, old, extracted_text='Late', extraction_version='test')
        current = row.operation_id
    assert tool.apply(owner, assistant, item.id, current, writers_stopped=True) == 'retain_attached_failed'
    assert not deleted


def test_wrong_owner_parent_and_stale_preview_have_no_side_effect(recovery):
    tool, _, owner, assistant, _, item, deleted, _ = recovery
    operation = removed(recovery)
    for requested_owner, parent in [(uuid4(), assistant), (owner, uuid4())]:
        with pytest.raises(KnowledgeNotFound):
            tool.apply(requested_owner, parent, item.id, operation, writers_stopped=True)
    with pytest.raises(KnowledgeStateConflict):
        tool.apply(owner, assistant, item.id, uuid4(), writers_stopped=True)
    assert not deleted


def test_future_reference_guard_or_key_mismatch_stops_before_storage(recovery):
    tool, _, owner, assistant, sessions, item, deleted, _ = recovery
    operation = removed(recovery)
    def future_guard(session):
        raise RecoveryBlocked('Future references need review')
    tool.guard = future_guard
    with pytest.raises(RecoveryBlocked):
        tool.apply(owner, assistant, item.id, operation, writers_stopped=True)
    tool.guard = lambda session: None
    with sessions.begin() as session:
        session.get(KnowledgeFile, item.id).object_key = 'another-owner/object'
    with pytest.raises(RecoveryBlocked):
        tool.apply(owner, assistant, item.id, operation, writers_stopped=True)
    assert not deleted


def test_storage_failure_retry_uses_same_key_and_new_claim(recovery):
    tool, _, owner, assistant, sessions, item, deleted, clock = recovery
    operation = removed(recovery)
    def fail(key):
        raise StorageUnavailable()
    tool.storage.remove_recorded_object = fail
    assert tool.apply(owner, assistant, item.id, operation, writers_stopped=True) == 'storage_failed_pending_retry'
    with sessions() as session:
        row = session.get(KnowledgeFile, item.id)
        assert row.cleanup_state == 'pending' and row.cleanup_error_code == 'storage_unavailable'
        assert row.cleanup_attempts == 1
        operation = row.operation_id
    clock[0] += timedelta(minutes=20)
    tool.storage.remove_recorded_object = lambda key: deleted.append(key)
    assert tool.apply(owner, assistant, item.id, operation, writers_stopped=True) == 'cleanup_complete'
    assert deleted == [item.object_key]


def test_db_failure_after_remote_delete_remains_recoverable(recovery, monkeypatch):
    tool, _, owner, assistant, sessions, item, deleted, clock = recovery
    operation = removed(recovery)
    finish = tool.finish
    def unavailable(*args, **kwargs):
        raise RuntimeError('Database unavailable')
    monkeypatch.setattr(tool, 'finish', unavailable)
    with pytest.raises(RuntimeError):
        tool.apply(owner, assistant, item.id, operation, writers_stopped=True)
    with sessions() as session:
        row = session.get(KnowledgeFile, item.id)
        assert row.cleanup_state == 'pending' and row.cleanup_attempts == 1
        operation = row.operation_id
    monkeypatch.setattr(tool, 'finish', finish)
    clock[0] += timedelta(minutes=20)
    assert tool.apply(owner, assistant, item.id, operation, writers_stopped=True) == 'cleanup_complete'
    assert deleted == [item.object_key, item.object_key]


def test_db_commit_failure_prevents_storage_call(recovery, monkeypatch):
    tool, _, owner, assistant, sessions, item, deleted, _ = recovery
    operation = removed(recovery)
    from sqlalchemy import event
    def fail(session):
        raise RuntimeError('Commit failed')
    event.listen(sessions.class_, 'before_commit', fail)
    try:
        with pytest.raises(RuntimeError):
            tool.apply(owner, assistant, item.id, operation, writers_stopped=True)
    finally:
        event.remove(sessions.class_, 'before_commit', fail)
    assert not deleted


def test_second_operator_cannot_delete_during_claim(recovery):
    tool, _, owner, assistant, sessions, item, deleted, _ = recovery
    old_operation = removed(recovery)
    def in_flight(key):
        with sessions() as session:
            current = session.get(KnowledgeFile, item.id).operation_id
        with pytest.raises(KnowledgeStateConflict):
            tool.apply(owner, assistant, item.id, old_operation, writers_stopped=True)
        assert tool.apply(owner, assistant, item.id, current, writers_stopped=True) == 'wait_for_quiet_period'
        deleted.append(key)
    tool.storage.remove_recorded_object = in_flight
    assert tool.apply(owner, assistant, item.id, old_operation, writers_stopped=True) == 'cleanup_complete'
    assert deleted == [item.object_key]


@pytest.mark.parametrize('body', [[], [{'name': 'owners/exact/original.pdf'}]])
def test_delete_adapter_exact_key_including_already_absent(body):
    def handler(request):
        assert request.method == 'DELETE'
        assert json.loads(request.content) == {'prefixes': ['owners/exact/original.pdf']}
        return httpx.Response(200, json=body)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        storage = SupabaseFileStorage('https://example.supabase.co', 'test', 'knowledge-files', client)
        storage.remove_recorded_object('owners/exact/original.pdf')


@pytest.mark.parametrize('status,body', [(403, []), (404, []), (500, []), (200, {}), (200, [{'name': 'wrong-file'}])])
def test_delete_adapter_does_not_hide_errors(status, body):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))) as client:
        storage = SupabaseFileStorage('https://example.supabase.co', 'test', 'knowledge-files', client)
        with pytest.raises(StorageUnavailable):
            storage.remove_recorded_object('owners/exact/original.pdf')


@pytest.mark.parametrize('drift', ['extra-table', 'extra-column', 'view', 'unsafe-rls'])
def test_real_guard_rejects_schema_or_security_drift(monkeypatch, drift):
    from assistant_builder.knowledge_recovery import phase2_schema_guard
    from assistant_builder.models import Base
    names = ['alembic_version', 'assistants', 'knowledge_files', 'knowledge_file_text']
    if drift == 'extra-table':
        names.append('published_snapshots')
    def columns(name, **kwargs):
        result = [{'name': column} for column in Base.metadata.tables[name].columns.keys()]
        if drift == 'extra-column':
            result.append({'name': 'published_references'})
        return result
    catalog = SimpleNamespace(get_table_names=lambda **kwargs: names,
        get_columns=columns, get_view_names=lambda **kwargs: ['references'] if drift == 'view' else [])
    monkeypatch.setattr('assistant_builder.knowledge_recovery.inspect', lambda connection: catalog)
    session = SimpleNamespace(connection=lambda: None, scalar=lambda *args, **kwargs: drift != 'unsafe-rls')
    with pytest.raises(RecoveryBlocked):
        phase2_schema_guard(session)
