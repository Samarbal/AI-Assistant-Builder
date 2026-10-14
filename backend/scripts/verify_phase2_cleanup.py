"""Verify cleanup of one successful live-test manifest; default is read-only.

Administrative connection is used ONLY in a read-only transaction to resolve
the recorded test assistants' owner IDs. All recovery uses assistant_runtime.
"""
import argparse
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from assistant_builder.config import Settings, MigrationSettings
from assistant_builder.db import validate_runtime_role
from assistant_builder.knowledge_recovery import KnowledgeRecovery, RecoveryBlocked
from assistant_builder.models import KnowledgeFile, KnowledgeFileText
from assistant_builder.storage import SupabaseFileStorage


def require(condition, message):
    if not condition:
        raise RecoveryBlocked(message)


def validate_manifest(source):
    UUID(source['run_id'])
    require(source['status'] == 'verified', 'Source verification did not pass')
    require(set(source['assistants']) == {'A', 'B'}, 'Expected two test assistants')
    require(len(source['files']) == 7, 'Expected seven recorded test artifacts')
    ids = set()
    for item in source['files']:
        require(item['assistant_id'] == source['assistants'][item['owner']], 'Manifest assistant mismatch')
        require(item['file_id'] not in ids, 'Duplicate manifest file')
        UUID(item['file_id'])
        UUID(item['assistant_id'])
        ids.add(item['file_id'])
    for label in ('A', 'B'):
        require(source['assistant_names'][label] == f"Phase2-live-{source['run_id']}-{label}", 'Unexpected test marker')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--writers-stopped', action='store_true')
    args = parser.parse_args()
    require(not args.apply or args.writers_stopped, 'Apply requires stopped upload producers')
    source = json.loads(args.source.read_text(encoding='utf-8'))
    validate_manifest(source)
    settings = Settings()
    host = urlparse(settings.supabase_url or '').hostname or ''
    require(host.endswith('.supabase.co'), 'Supabase project required')
    migration_url = MigrationSettings().migration_database_url
    for url in (settings.database_url, migration_url):
        parsed = make_url(url)
        require(parsed.host == 'db.' + host or (parsed.username or '').endswith('.' + host.split('.')[0]), 'Database/project mismatch')
    runtime = create_engine(settings.database_url, hide_parameters=True, pool_pre_ping=True)
    admin = create_engine(migration_url, hide_parameters=True)
    storage = None
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = args.source.with_name('PHASE-2-CLEANUP-' + source['run_id'] + ('-APPLY-' if args.apply else '-PREFLIGHT-') + stamp + '.json')
    require(not output.exists(), 'Evidence already exists; review it before another run')
    report = {'source_run_id': source['run_id'], 'started_at': datetime.now(timezone.utc).isoformat(),
              'mode': 'apply' if args.apply else 'preflight', 'status': 'incomplete', 'passed': [], 'files': []}

    def save():
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        temporary.replace(output)

    def passed(label):
        report['passed'].append(label)
        save()
        print('PASS:', label, flush=True)

    try:
        validate_runtime_role(runtime)
        owners = {}
        control = json.loads(args.source.with_name('PHASE-2-UPLOAD-LIVE-RESULTS.json').read_text())
        with admin.begin() as connection:
            connection.execute(text('SET TRANSACTION READ ONLY'))
            require(connection.scalar(text('SELECT version_num FROM public.alembic_version')) == '0003_knowledge_files', 'Unexpected migration revision')
            for label, assistant in source['assistants'].items():
                row = connection.execute(text('SELECT owner_id, name, state FROM public.assistants WHERE id=:id'), {'id': UUID(assistant)}).one()
                require(row.name == source['assistant_names'][label] and row.state == 'draft', 'Test assistant identity changed')
                owners[label] = row.owner_id
            control_owner = connection.scalar(text('SELECT owner_id FROM public.assistants WHERE id=:id'), {'id': UUID(control['retained_assistant_id'])})
            require(control_owner is not None, 'Control assistant missing')
        admin.dispose()
        require(owners['A'] != owners['B'], 'Owners are not distinct')
        storage = SupabaseFileStorage(settings.supabase_url, settings.supabase_storage_key, settings.supabase_storage_bucket)
        recovery = KnowledgeRecovery(sessionmaker(runtime, expire_on_commit=False), storage)

        def read(owner, file_id):
            with recovery.transaction(owner, readonly=True) as session:
                recovery.guard(session)
                row = session.get(KnowledgeFile, UUID(str(file_id)))
                require(row is not None, 'Recorded file inaccessible')
                extracted = session.get(KnowledgeFileText, row.id)
                require(extracted is not None, 'Extracted text missing')
                fingerprint = (row.owner_id, row.assistant_id, row.object_key, row.content_sha256,
                               row.removed_at, row.slot_number, hashlib.sha256(extracted.extracted_text.encode()).hexdigest())
                return row, fingerprint

        def verify_original(row):
            response = storage.client.get(storage.base_url + '/object/' + storage.bucket + '/' + row.object_key)
            require(response.status_code == 200, 'Expected original inaccessible')
            require(hashlib.sha256(response.content).hexdigest() == row.content_sha256, 'Original content differs')

        control_row, control_before = read(control_owner, control['retained_file_id'])
        require(str(control_row.id) not in {f['file_id'] for f in source['files']}, 'Control overlaps cleanup targets')
        verify_original(control_row)
        prepared = []
        for label in ('A', 'B'):
            preview = recovery.preview(owners[label], UUID(source['assistants'][label]))
            expected = {f['file_id'] for f in source['files'] if f['owner'] == label}
            require({p['file_id'] for p in preview} == expected, 'Cleanup candidates differ from manifest')
            for candidate in preview:
                require(candidate['action'] == 'delete_recorded_original', 'Candidate not yet eligible')
                row, fingerprint = read(owners[label], candidate['file_id'])
                require(row.removed_at is not None and row.slot_number is None and row.cleanup_state == 'pending', 'Unexpected attachment state')
                require(row.cleanup_attempts == 0, 'Previous cleanup attempt needs review')
                verify_original(row)
                prepared.append((owners[label], row, fingerprint))
                report['files'].append({'file_id': str(row.id), 'action': candidate['action'], 'result': 'not_applied'})
                save()
                print('Preflight artifact verified:', str(row.id), flush=True)
        passed('Read-only preflight: revision 0003, runtime RLS guard, seven exact removed artifacts eligible; originals match; unrelated control intact')
        if args.apply:
            for index, (owner, row, fingerprint) in enumerate(prepared):
                result = recovery.apply(owner, row.assistant_id, row.id, row.operation_id, writers_stopped=True)
                report['files'][index]['result'] = result
                save()
                require(result == 'cleanup_complete', 'Recovery did not complete; stop before remaining files')
                after, after_fingerprint = read(owner, row.id)
                require(after_fingerprint == fingerprint and after.cleanup_state == 'complete' and after.cleanup_attempts == 1, 'Cleanup metadata/text postcondition failed')
                response = storage.client.post(storage.base_url + '/object/list/' + storage.bucket,
                    json={'prefix': row.object_key.rsplit('/', 1)[0], 'limit': 2, 'offset': 0})
                require(response.status_code == 200 and response.json() == [], 'Exact object directory not empty')
                repeat = recovery.apply(owner, row.assistant_id, row.id, after.operation_id, writers_stopped=True)
                require(repeat == 'already_complete', 'Completed-operation repeat failed')
                report['files'][index]['repeat'] = repeat
                report['files'][index]['object_absent'] = True
                passed('Exact artifact cleaned and repeat safe: ' + str(row.id))
            for label in ('A', 'B'):
                require(recovery.preview(owners[label], UUID(source['assistants'][label])) == [], 'Remaining pending test operations')
            require(read(control_owner, control_row.id)[1] == control_before, 'Unrelated control metadata changed')
            verify_original(control_row)
            passed('Both test assistants have no pending operations; metadata/text retained; unrelated control bytes and metadata unchanged')
        report['status'] = 'verified'
    except Exception as exc:
        report['status'] = 'failed'
        report['failure_type'] = type(exc).__name__
        if isinstance(exc, RecoveryBlocked):
            report['failure'] = str(exc)
            print('STOP:', str(exc))
        raise
    finally:
        save()
        if storage:
            storage.close()
        admin.dispose()
        runtime.dispose()
        print('Sanitized report:', output.name)


if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    try:
        main()
    except Exception as exc:
        print('STOP: cleanup verification incomplete. Error type:', type(exc).__name__)
        raise SystemExit(1) from None
