"""Operator-invoked, owner-scoped reconciliation. Not registered in the HTTP API.

Apply requires a maintenance window: all upload producers must be stopped and
outstanding Storage writes settled. A DB lease cannot fence a late remote upload.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import inspect, or_, select, text

from .db import set_owner_identity
from .knowledge_repository import KnowledgeRepository, KnowledgeStateConflict
from .models import Assistant, KnowledgeFile, PublishedSource
from .storage import StorageUnavailable


class RecoveryBlocked(Exception):
    pass


def utc(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def phase2_schema_guard(session):
    """Fail closed unless the reviewed Phase 2-4 additive schema is present."""
    catalog = inspect(session.connection())
    expected_public_tables = {
            'alembic_version', 'assistants', 'knowledge_files', 'knowledge_file_text',
            'knowledge_indexes', 'knowledge_index_sources', 'knowledge_index_batches',
            'knowledge_chunks', 'assistant_publications', 'published_snapshots',
            'published_sources', 'publication_requests', 'visitor_conversations', 'visitor_turns'}
    expected_accounting_tables = {'price_versions', 'budget_days', 'budget_operations',
                                  'budget_attempts', 'budget_day_holds'}
    if (set(catalog.get_table_names(schema='public')) != expected_public_tables
            or set(catalog.get_table_names(schema='ai_accounting')) != expected_accounting_tables):
        raise RecoveryBlocked('Schema changed; reference-aware cleanup review required')
    # Frozen baseline, intentionally not derived from evolving ORM models.
    expected_columns = {
        'assistants': set('id owner_id name role colors response_style tone fallback_message state created_at updated_at active_knowledge_index_id'.split()),
        'knowledge_files': set('id owner_id assistant_id slot_number original_filename file_format size_bytes content_sha256 object_key processing_state error_code operation_id lease_expires_at removed_at cleanup_state cleanup_attempts cleanup_error_code created_at updated_at'.split()),
        'knowledge_file_text': set('file_id assistant_id owner_id extracted_text extraction_version created_at'.split()),
        'knowledge_indexes': set('id owner_id assistant_id version idempotency_key manifest_sha256 embedding_provider embedding_model vector_dimension tokenizer_version chunker_version state operation_id lease_expires_at total_chunks completed_chunks reserved_cost_microusd error_code created_at updated_at ready_at'.split()),
        'knowledge_index_sources': set('index_id file_id assistant_id owner_id extraction_version source_sha256'.split()),
        'knowledge_index_batches': set('id index_id assistant_id owner_id batch_number idempotency_key request_sha256 chunk_ids reserved_tokens reserved_cost_microusd state operation_id lease_expires_at attempts actual_tokens error_code created_at updated_at'.split()),
        'knowledge_chunks': set('id index_id owner_id assistant_id file_id ordinal extraction_version chunker_version source_sha256 start_offset end_offset token_count text_sha256 chunk_text embedding'.split()),
        'assistant_publications': set('id public_id assistant_id owner_id active_snapshot_id created_at updated_at'.split()),
        'published_snapshots': set('id assistant_id owner_id version state config draft_fingerprint knowledge_index_id embedding_provider embedding_model vector_dimension retrieval_min_similarity manifest_sha256 source_count created_at activated_at build_xid'.split()),
        'published_sources': set('snapshot_id file_id assistant_id owner_id index_id source_sha256 extraction_version created_at'.split()),
        'publication_requests': set('id assistant_id owner_id idempotency_key request_sha256 snapshot_id created_at'.split()),
        'visitor_conversations': set('id publication_id assistant_id owner_id token_sha256 expires_at created_at'.split()),
        'visitor_turns': set('id conversation_id publication_id snapshot_id assistant_id owner_id request_id input_sha256 user_text state answer_text outcome error_code created_at completed_at'.split()),
    }
    accounting_columns = {
        'price_versions': set('id provider model input_microusd_per_million output_microusd_per_million embedding_microusd_per_million message_cap_microusd index_cap_microusd daily_cap_microusd valid_from valid_until'.split()),
        'budget_days': set('day_utc held_microusd charged_microusd'.split()),
        'budget_operations': set('id caller_role scope_sha256 kind price_version operation_cap_microusd held_microusd charged_microusd state created_at'.split()),
        'budget_attempts': set('id operation_id caller_role scope_sha256 price_version request_sha256 kind model max_input_tokens max_output_tokens held_microusd charged_microusd state created_at dispatched_at settled_at input_tokens output_tokens'.split()),
        'budget_day_holds': set('attempt_id day_utc held_microusd charged_microusd'.split()),
    }
    if catalog.get_view_names(schema='public'):
        raise RecoveryBlocked('Schema changed; reference-aware cleanup review required')
    for name, expected in expected_columns.items():
        columns = {column['name'] for column in catalog.get_columns(name, schema='public')}
        if columns != expected:
            raise RecoveryBlocked('Schema changed; reference-aware cleanup review required')
        protected = session.scalar(text('''SELECT relrowsecurity AND relforcerowsecurity
            AND relowner <> (SELECT oid FROM pg_roles WHERE rolname=current_user)
            FROM pg_class WHERE oid=to_regclass(:table)'''), {'table': 'public.' + name})
        if protected is not True:
            raise RecoveryBlocked('Owner RLS boundary differs from the approved baseline')
    for name, expected in accounting_columns.items():
        columns = {column['name'] for column in catalog.get_columns(name, schema='ai_accounting')}
        if columns != expected:
            raise RecoveryBlocked('Accounting schema changed; operator review required')
        protected = session.scalar(text('''SELECT relrowsecurity AND relforcerowsecurity
            FROM pg_class WHERE oid=to_regclass(:table)'''), {'table': 'ai_accounting.' + name})
        if protected is not True:
            raise RecoveryBlocked('Accounting RLS boundary differs from the approved baseline')
    role_state = session.execute(text('''SELECT rolcanlogin,rolsuper,rolbypassrls,rolinherit,
        rolcreatedb,rolcreaterole,rolreplication FROM pg_roles
        WHERE rolname='assistant_public_runtime' ''')).one_or_none()
    executor_state = session.execute(text('''SELECT rolcanlogin,rolsuper,rolbypassrls,rolinherit,
        rolcreatedb,rolcreaterole,rolreplication FROM pg_roles
        WHERE rolname='assistant_budget_executor' ''')).one_or_none()
    if role_state != (True, False, False, False, False, False, False) or executor_state != (False, False, False, False, False, False, False):
        raise RecoveryBlocked('P4 runtime role attributes differ from the approved baseline')
    if session.scalar(text("SELECT has_any_column_privilege('assistant_runtime','ai_accounting.budget_attempts','SELECT') OR has_table_privilege('assistant_runtime','ai_accounting.budget_attempts','SELECT')")):
        raise RecoveryBlocked('Owner runtime has direct accounting access')
    if session.scalar(text("SELECT has_any_column_privilege('assistant_public_runtime','ai_accounting.budget_attempts','SELECT') OR has_table_privilege('assistant_public_runtime','ai_accounting.budget_attempts','SELECT')")):
        raise RecoveryBlocked('Public runtime has direct accounting access')
    vector_schema = session.scalar(text('''SELECT n.nspname FROM pg_extension e
        JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector' '''))
    if vector_schema != 'public':
        raise RecoveryBlocked('pgvector schema differs from the reviewed index baseline')


def action_for(item, now):
    if item.cleanup_state == 'complete':
        return 'already_complete'
    if item.removed_at is not None:
        # Also lets previously issued URLs expire (maximum supported TTL 300s).
        deadline = max(utc(item.lease_expires_at), utc(item.removed_at)) + timedelta(minutes=5)
        if now <= deadline:
            return 'wait_for_quiet_period'
        return 'delete_recorded_original' if item.cleanup_state == 'pending' else 'no_action'
    if item.processing_state in {'accepted', 'processing'} and utc(item.lease_expires_at) < now:
        return 'mark_expired_failed'
    if item.processing_state == 'failed':
        return 'retain_attached_failed'
    return 'no_action'


class KnowledgeRecovery:
    def __init__(self, sessions, storage=None, *, guard=phase2_schema_guard,
                 clock=lambda: datetime.now(timezone.utc)):
        self.sessions, self.storage, self.guard, self.clock = sessions, storage, guard, clock

    @contextmanager
    def transaction(self, owner, *, readonly=False):
        with self.sessions.begin() as session:
            if readonly and session.bind.dialect.name == 'postgresql':
                session.execute(text('SET TRANSACTION READ ONLY'))
            set_owner_identity(session, owner)
            if session.bind.dialect.name == 'postgresql':
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
            yield session

    def validate(self, session, owner, assistant, item):
        self.guard(session)
        parent = session.scalar(select(Assistant).where(Assistant.id == assistant, Assistant.owner_id == owner))
        if parent is None or parent.state != 'draft':
            raise RecoveryBlocked('Only the current Phase 2 draft architecture permits cleanup')
        expected = f'owners/{owner}/assistants/{assistant}/files/{item.id}/original.{item.file_format}'
        if item.object_key != expected or item.file_format not in {'pdf', 'docx'}:
            raise RecoveryBlocked('Recorded object identity differs from the expected immutable path')
        if session.scalar(select(PublishedSource.snapshot_id).where(
                PublishedSource.owner_id == owner,
                PublishedSource.assistant_id == assistant,
                PublishedSource.file_id == item.id).limit(1)) is not None:
            raise RecoveryBlocked('Knowledge artifact is retained by a published snapshot')

    def preview(self, owner, assistant, *, limit=100):
        with self.transaction(owner, readonly=True) as session:
            self.guard(session)
            rows = session.scalars(select(KnowledgeFile).where(
                KnowledgeFile.owner_id == owner, KnowledgeFile.assistant_id == assistant,
                or_(KnowledgeFile.cleanup_state == 'pending',
                    KnowledgeFile.processing_state.in_(['accepted', 'processing']))
            ).order_by(KnowledgeFile.created_at, KnowledgeFile.id).limit(limit)).all()
            result = []
            for item in rows:
                self.validate(session, owner, assistant, item)
                result.append({'file_id': str(item.id), 'operation_id': str(item.operation_id),
                               'action': action_for(item, self.clock()),
                               'cleanup_attempts': item.cleanup_attempts})
            return result

    def apply(self, owner, assistant, file_id, expected_operation, *, writers_stopped=False):
        if not writers_stopped:
            raise RecoveryBlocked('Stop upload producers and settle outstanding Storage writes first')
        with self.transaction(owner) as session:
            item = KnowledgeRepository(session).get_for_owner(owner, assistant, file_id, include_removed=True, lock=True)
            self.validate(session, owner, assistant, item)
            if item.operation_id != expected_operation:
                raise KnowledgeStateConflict()
            action = action_for(item, self.clock())
            if action not in {'mark_expired_failed', 'delete_recorded_original'}:
                return action
            if action == 'delete_recorded_original' and self.storage is None:
                raise StorageUnavailable()
            claim = uuid4()
            item.operation_id = claim
            if item.processing_state in {'accepted', 'processing'}:
                item.processing_state = 'failed'
                item.error_code = 'processing_timeout'
            item.cleanup_state = 'pending'
            if action == 'mark_expired_failed':
                return action  # Keep the attachment/slot; never silently detach it.
            item.cleanup_attempts += 1
            item.cleanup_error_code = None
            item.lease_expires_at = self.clock() + timedelta(minutes=5)
            key = item.object_key
        # Claim must commit successfully before any remote deletion.
        try:
            self.storage.remove_recorded_object(key)
        except StorageUnavailable:
            self.finish(owner, assistant, file_id, claim, failed=True)
            return 'storage_failed_pending_retry'
        self.finish(owner, assistant, file_id, claim, failed=False)
        return 'cleanup_complete'

    def finish(self, owner, assistant, file_id, claim, *, failed):
        # If this transaction fails, the durable pending claim remains retryable.
        with self.transaction(owner) as session:
            item = KnowledgeRepository(session).get_for_owner(owner, assistant, file_id, include_removed=True, lock=True)
            self.validate(session, owner, assistant, item)
            if item.operation_id != claim or item.removed_at is None:
                raise KnowledgeStateConflict()
            item.cleanup_state = 'pending' if failed else 'complete'
            item.cleanup_error_code = 'storage_unavailable' if failed else None
        # Keep metadata and extracted text for audit/future lifecycle decisions.
