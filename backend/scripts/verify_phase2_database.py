"""Live runtime-role tests. All generated data is rolled back, never deleted."""
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError
from assistant_builder.config import Settings
from assistant_builder.db import set_owner_identity, validate_runtime_role
from assistant_builder.models import Assistant, KnowledgeFile, KnowledgeFileText
from assistant_builder.knowledge_repository import KnowledgeRepository, KnowledgeLimitReached


def main():
    engine = create_engine(Settings().database_url, hide_parameters=True, pool_size=1, max_overflow=0)
    try:
        validate_runtime_role(engine)
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT current_user')) == 'assistant_runtime'
            for name in ('knowledge_files', 'knowledge_file_text'):
                assert connection.scalar(text('SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:t)'), {'t':'public.'+name})
                assert not connection.scalar(text('SELECT has_table_privilege(current_user,:t,\'DELETE\')'), {'t':'public.'+name})
                assert not connection.scalar(text('SELECT has_column_privilege(current_user,:t,\'owner_id\',\'UPDATE\')'), {'t':'public.'+name})
        print('PASS: actual runtime login, forced RLS, no DELETE or owner_id UPDATE')
        owner, other, assistant_id = uuid4(), uuid4(), uuid4()
        with Session(engine) as session:
            try:
                set_owner_identity(session, owner)
                session.add(Assistant(id=assistant_id, owner_id=owner, name='Transient Phase 2 check', role='support', colors={}, response_style='brief', tone='friendly', fallback_message='Unknown'))
                session.flush()
                repo = KnowledgeRepository(session)
                items = [repo.reserve(owner, assistant_id, filename='test.pdf', file_format='pdf', size_bytes=100,
                    content_sha256='a'*64, lease_expires_at=datetime.now(timezone.utc)+timedelta(minutes=5)) for _ in range(5)]
                try:
                    repo.reserve(owner, assistant_id, filename='sixth.pdf', file_format='pdf', size_bytes=100,
                        content_sha256='a'*64, lease_expires_at=datetime.now(timezone.utc)+timedelta(minutes=5))
                    raise AssertionError('Sixth reservation accepted')
                except KnowledgeLimitReached:
                    pass
                first = items[0]
                repo.start_processing(owner, assistant_id, first.id, first.operation_id)
                repo.complete_extraction(owner, assistant_id, first.id, first.operation_id, extracted_text='Fixture text', extraction_version='test-v1')
                print('PASS: five-slot limit and extracted text persisted inside transaction')
                for sql in (
                    'UPDATE public.knowledge_files SET owner_id=owner_id WHERE id=:id',
                    'DELETE FROM public.knowledge_files WHERE id=:id',
                    'UPDATE public.knowledge_files SET slot_number=6 WHERE id=:id',
                    'UPDATE public.knowledge_files SET slot_number=2 WHERE id=:id',
                ):
                    try:
                        with session.begin_nested():
                            session.execute(text(sql), {'id': first.id})
                        raise AssertionError('Forbidden operation accepted')
                    except DBAPIError:
                        pass
                print('PASS: immutable ownership, DELETE prohibition, slot range and uniqueness constraints')
                set_owner_identity(session, other)
                assert session.scalar(select(KnowledgeFile.id).where(KnowledgeFile.assistant_id == assistant_id)) is None
                assert session.scalar(select(KnowledgeFileText.file_id).where(KnowledgeFileText.assistant_id == assistant_id)) is None
                session.execute(text("SELECT set_config('app.owner_id','',true)"))
                assert session.scalar(select(KnowledgeFile.id).where(KnowledgeFile.assistant_id == assistant_id)) is None
                print('PASS: other-owner and missing-identity queries see no fixture metadata/text')
            finally:
                session.rollback()
        with Session(engine) as session:
            set_owner_identity(session, owner)
            assert session.get(Assistant, assistant_id) is None
        print('PASS: all transient fixtures rolled back; no existing records changed')
    finally:
        engine.dispose()


if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    try:
        main()
    except Exception as exc:
        print('FAIL: live database check. Error type:', type(exc).__name__)
        raise SystemExit(1) from None
