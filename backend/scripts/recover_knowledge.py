"""Dry-run by default. Apply targets one reviewed file/operation, never a bucket sweep."""
import argparse
import json
import logging
from uuid import UUID
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from assistant_builder.config import Settings
from assistant_builder.db import validate_runtime_role
from assistant_builder.knowledge_recovery import KnowledgeRecovery, RecoveryBlocked
from assistant_builder.storage import SupabaseFileStorage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-id', type=UUID, required=True)
    parser.add_argument('--assistant-id', type=UUID, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--file-id', type=UUID)
    parser.add_argument('--operation-id', type=UUID)
    parser.add_argument('--writers-stopped', action='store_true', help='Acknowledge a maintenance window with all writers stopped and remote uploads settled')
    args = parser.parse_args()
    if args.apply and not (args.file_id and args.operation_id and args.writers_stopped):
        parser.error('--apply requires --file-id, --operation-id and --writers-stopped')
    settings = Settings()
    db_url = make_url(settings.database_url)
    project = urlparse(settings.supabase_url or '').hostname or ''
    ref = project.split('.')[0]
    if not project.endswith('.supabase.co') or not (
            db_url.host == f'db.{ref}.supabase.co' or (db_url.username or '').endswith('.' + ref)):
        raise RecoveryBlocked('Database and Storage project identity must match')
    engine = create_engine(settings.database_url, hide_parameters=True, pool_pre_ping=True)
    storage = None
    try:
        validate_runtime_role(engine)
        if args.apply:
            if not settings.supabase_storage_key:
                raise RecoveryBlocked('Server Storage key required for apply')
            storage = SupabaseFileStorage(settings.supabase_url, settings.supabase_storage_key, settings.supabase_storage_bucket)
        recovery = KnowledgeRecovery(sessionmaker(engine, expire_on_commit=False), storage)
        if args.apply:
            result = recovery.apply(args.owner_id, args.assistant_id, args.file_id,
                                    args.operation_id, writers_stopped=args.writers_stopped)
            print(json.dumps({'file_id': str(args.file_id), 'result': result}))
            return 1 if result == 'storage_failed_pending_retry' else 0
        rows = recovery.preview(args.owner_id, args.assistant_id)
        print(json.dumps({'mode': 'dry-run', 'limit': 100, 'operations': rows}, indent=2))
        print('No database updates or Storage requests performed. At most 100 records shown.')
        return 0
    finally:
        if storage:
            storage.close()
        engine.dispose()


if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    try:
        raise SystemExit(main())
    except RecoveryBlocked as exc:
        print('STOP:', str(exc))
        raise SystemExit(1) from None
    except Exception as exc:
        print('STOP: recovery failed; inspect dry-run before retry. Error type:', type(exc).__name__)
        raise SystemExit(1) from None
