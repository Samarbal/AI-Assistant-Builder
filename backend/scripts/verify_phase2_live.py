"""Interactive two-owner HTTP verification; only newly generated fixtures mutate.

No migrations/admin SQL, API overrides, physical deletion or credential persistence.
Successful runs logically detach generated files and retain a cleanup preview.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import getpass
from hashlib import sha256
from io import BytesIO
import json
import logging
from pathlib import Path
import socket
import sys
from threading import Barrier, Thread
import time
from uuid import UUID, uuid4
import warnings

from docx import Document
import httpx
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
import uvicorn
from urllib.parse import urlparse

from assistant_builder.auth import SupabaseAuthVerifier
from assistant_builder.config import Settings
from assistant_builder.db import set_owner_identity, validate_runtime_role
from assistant_builder.knowledge_recovery import KnowledgeRecovery
from assistant_builder.main import create_app
from assistant_builder.models import KnowledgeFile, KnowledgeFileText
from assistant_builder.storage import SupabaseFileStorage, MIME_TYPES
from signin_phase1 import sign_in, validate_auth_settings


class VerificationFailure(Exception):
    """Messages must be developer-written labels, never provider response bodies."""


def require(condition, label):
    if not condition:
        raise VerificationFailure(label)


def fixture_document(kind):
    stream = BytesIO()
    if kind == 'docx':
        document = Document()
        document.add_paragraph('Phase 2 fixture: opening hours are nine to five.')
        document.save(stream)
    else:
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        content = DecodedStreamObject()
        content.set_data(b'BT /F1 12 Tf 10 200 Td (Phase 2 fixture: nine to five.) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(content)
        writer.write(stream)
    return stream.getvalue()


@contextmanager
def live_server(app):
    """Bound loopback socket avoids port races; real HTTP, no TestClient overrides."""
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False,
        log_level='critical', timeout_graceful_shutdown=30))
    thread = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 120
        while not server.started:
            require(thread.is_alive() and time.monotonic() < deadline, 'Temporary API startup failed')
            time.sleep(0.1)
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit = True
        thread.join(timeout=35)
        listener.close()


def concurrent_uploads(base_url, token, path, documents):
    gate = Barrier(3, timeout=15)
    def send(document):
        name, content = document
        with httpx.Client(base_url=base_url, timeout=120, headers={'Authorization': 'Bearer ' + token}) as client:
            gate.wait()
            start = time.monotonic()
            response = client.post(path, files={'file': (name, content, MIME_TYPES['docx'])})
            return name, response, start, time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(send, doc) for doc in documents]
        gate.wait()
        results = [future.result() for future in futures]
    return results


class LiveChecks:
    def __init__(self, clients, owners, tokens, base_url, sessions, storage, report, save):
        self.clients, self.owners, self.tokens, self.base_url = clients, owners, tokens, base_url
        self.sessions, self.storage, self.report, self.save = sessions, storage, report, save

    def passed(self, label):
        self.report['passed'].append(label)
        self.save()
        print('PASS:', label, flush=True)

    def files(self, label, assistant):
        response = self.clients[label].get(f'/assistants/{assistant}/knowledge-files')
        require(response.status_code == 200, 'Owner file listing failed')
        return response.json()

    def upload(self, label, assistant, name, kind='docx'):
        self.report['attempted_uploads'].append({'assistant_id': assistant, 'filename': name})
        self.save()
        response = self.clients[label].post(f'/assistants/{assistant}/knowledge-files',
            files={'file': (name, fixture_document(kind), MIME_TYPES[kind])})
        require(response.status_code == 201, 'Fixture upload did not return 201')
        item = response.json()
        self.report['files'].append({'owner': label, 'assistant_id': assistant, 'file_id': str(UUID(item['id']))})
        self.save()
        require(item['processing_state'] == 'extracted', 'Fixture text extraction incomplete')
        return item

    def rows(self, label, assistant):
        with self.sessions.begin() as session:
            set_owner_identity(session, self.owners[label])
            return session.scalars(select(KnowledgeFile).where(KnowledgeFile.assistant_id == UUID(assistant))).all()

    def run(self):
        assistants = {}
        for label in ('A', 'B'):
            name = f"Phase2-live-{self.report['run_id']}-{label}"
            self.report['assistant_names'][label] = name
            self.save()  # Also records intent if HTTP commit succeeds but response is lost.
            response = self.clients[label].post('/assistants', json={'name': name,
                'role': 'Support', 'colors': {}, 'response_style': 'Brief', 'tone': 'Friendly', 'fallback_message': 'Unknown'})
            require(response.status_code == 201, 'Fixture assistant creation failed')
            assistant = str(UUID(response.json()['id']))
            assistants[label] = assistant
            self.report['assistants'][label] = assistant
            self.save()
        first = {label: self.upload(label, assistants[label], f'initial-{label}.{kind}', kind)
                 for label, kind in [('A', 'docx'), ('B', 'pdf')]}
        self.passed('Real owner A DOCX and owner B PDF uploaded/extracted through HTTP')

        for outsider, target in [('B', 'A'), ('A', 'B')]:
            assistant, file_id = assistants[target], first[target]['id']
            path = f'/assistants/{assistant}/knowledge-files'
            client = self.clients[outsider]
            for request in (lambda: client.get(path),
                    lambda: client.post(path, files={'file': ('denied.docx', fixture_document('docx'), MIME_TYPES['docx'])}),
                    lambda: client.delete(path + '/' + file_id), lambda: client.post(path + '/' + file_id + '/download-url')):
                response = request()
                require(response.status_code == 404, 'SECURITY: cross-owner operation was not denied with 404')
            require([f['id'] for f in self.files(target, assistant)] == [file_id], 'SECURITY: target files changed')
            require(len(self.rows(target, assistant)) == 1, 'Denied request left extra metadata')
            require(self.rows(outsider, assistant) == [], 'SECURITY: raw runtime query crossed owner boundary')
        self.passed('Both directions: cross-owner list/upload/delete/sign denied; owner data unchanged; raw RLS isolated')

        assistant = assistants['A']
        path = f'/assistants/{assistant}/knowledge-files'
        file_id = first['A']['id']
        signed = self.clients['A'].post(path + '/' + file_id + '/download-url')
        require(signed.status_code == 200 and signed.headers.get('cache-control') == 'no-store', 'Owner signed download failed')
        with httpx.Client(timeout=30) as downloader:
            data = downloader.get(signed.json()['download_url'])
            row = self.rows('A', assistant)[0]
            require(data.status_code == 200 and sha256(data.content).hexdigest() == row.content_sha256,
                    'Owner signed download content mismatch')
        self.passed('Authenticated owner signed download returns original bytes')
        for _ in range(2):
            require(self.clients['A'].delete(path + '/' + file_id).status_code == 204, 'Logical deletion/idempotency failed')
        require(self.files('A', assistant) == [], 'Removed file still listed')
        require(self.clients['A'].post(path + '/' + file_id + '/download-url').status_code == 404, 'Removed file received a new URL')
        row = self.rows('A', assistant)[0]
        require(row.removed_at is not None and row.slot_number is None and row.cleanup_state == 'pending', 'Logical deletion metadata incorrect')
        replacement = self.upload('A', assistant, 'replacement.pdf', 'pdf')
        require(replacement['id'] != file_id and [f['id'] for f in self.files('A', assistant)] == [replacement['id']], 'Replacement association incorrect')
        self.passed('Logical removal, repeated DELETE, new-link denial and PDF replacement verified')
        for number in range(3):
            self.upload('A', assistant, f'fill-{number}.docx')
        require(len(self.files('A', assistant)) == 4, 'Race setup requires exactly four attachments')
        documents = [(f'race-{i}.docx', fixture_document('docx')) for i in range(2)]
        self.report['attempted_uploads'].extend({'assistant_id': assistant, 'filename': name} for name, _ in documents)
        self.save()
        results = concurrent_uploads(self.base_url, self.tokens['A'], path, documents)
        for name, response, start, end in results:
            if response.status_code == 201:
                self.report['files'].append({'owner': 'A', 'assistant_id': assistant, 'file_id': str(UUID(response.json()['id']))})
        self.report['race'] = {'status_codes': sorted(r.status_code for _, r, _, _ in results),
            'overlap_seconds': round(min(end for _, _, _, end in results) - max(start for _, _, start, _ in results), 4)}
        self.save()
        require(self.report['race']['status_codes'] == [201, 409], 'Concurrent fifth-slot requests did not produce 201/409')
        require(self.report['race']['overlap_seconds'] > 0, 'Requests did not overlap; race verification inconclusive')
        rows = self.rows('A', assistant)
        active = [r for r in rows if r.removed_at is None]
        loser = next(name for name, response, _, _ in results if response.status_code == 409)
        require(len(rows) == 6 and len(active) == 5 and {r.slot_number for r in active} == set(range(1, 6)), 'Five-slot database invariant failed')
        require(all(r.processing_state == 'extracted' for r in active), 'Concurrent winner not extracted')
        require(all(r.original_filename != loser for r in rows), 'Rejected upload left metadata')
        for label in ('A', 'B'):
            expected = self.rows(label, assistants[label])
            prefix = f'owners/{self.owners[label]}/assistants/{assistants[label]}/files'
            listing = self.storage.client.post(self.storage.base_url + '/object/list/' + self.storage.bucket,
                json={'prefix': prefix, 'limit': 100, 'offset': 0})
            require(listing.status_code == 200, 'Exact test-prefix Storage inventory failed')
            require({item['name'] for item in listing.json()} == {str(item.id) for item in expected}, 'Unexpected or missing Storage artifact in test prefix')
            with self.sessions.begin() as session:
                set_owner_identity(session, self.owners[label])
                texts = session.scalars(select(KnowledgeFileText.file_id).where(KnowledgeFileText.assistant_id == UUID(assistants[label]))).all()
                require(set(texts) == {item.id for item in expected}, 'Extracted text persistence mismatch')
        self.passed('Overlapping uploads: exactly one 201 and one 409; five slots; no rejected-upload metadata or orphan directory')

        # Only this run's tracked IDs; no deletion of original Storage objects.
        for item in self.report['files']:
            target = f"/assistants/{item['assistant_id']}/knowledge-files/{item['file_id']}"
            require(self.clients[item['owner']].delete(target).status_code == 204, 'Fixture logical cleanup failed')
        recovery = KnowledgeRecovery(self.sessions)
        for label in ('A', 'B'):
            require(self.files(label, assistants[label]) == [], 'Generated attachment cleanup incomplete')
            self.report['cleanup_preview'][label] = recovery.preview(self.owners[label], UUID(assistants[label]))
        self.passed('Only current-run files logically detached; physical cleanup preview retained, no Storage deletion')


def main():
    logging.disable(logging.CRITICAL)
    warnings.filterwarnings('error', category=getpass.GetPassWarning)
    require(sys.stdin.isatty(), 'Interactive terminal required for hidden password entry')
    settings = Settings()
    validate_auth_settings(settings)
    require(bool(settings.supabase_storage_key), 'Storage key is not configured')
    db_url = make_url(settings.database_url)
    host = urlparse(settings.supabase_url).hostname or ''
    ref = host.split('.')[0]
    require(host.endswith('.supabase.co') and (db_url.host == 'db.' + host or (db_url.username or '').endswith('.' + ref)), 'Supabase database/project mismatch')
    run_id = str(uuid4())
    report = {'run_id': run_id, 'started_at': datetime.now(timezone.utc).isoformat(),
        'status': 'incomplete', 'passed': [], 'assistant_names': {}, 'assistants': {}, 'files': [],
        'attempted_uploads': [], 'cleanup_preview': {}, 'physical_cleanup': 'not_performed'}
    target = Path(__file__).resolve().parents[2] / 'docs/ai-sdlc/contracts' / f'PHASE-2-LIVE-{run_id}.json'
    def save():
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        temp.replace(target)
    engine = None
    storage = None
    clients = {}
    try:
        tokens, owners = {}, {}
        with httpx.Client(timeout=20) as auth:
            for label in ('A', 'B'):
                email = input(f'Test owner {label} email: ').strip()
                password = getpass.getpass(f'Test owner {label} password (hidden): ')
                tokens[label] = sign_in(auth, settings.supabase_url, settings.supabase_anon_key, email, password)
                del email, password
                owners[label] = SupabaseAuthVerifier(settings.supabase_url, settings.supabase_anon_key, auth).verify('Bearer ' + tokens[label]).owner_id
        require(owners['A'] != owners['B'], 'Two distinct authenticated owners required')
        engine = create_engine(settings.database_url, hide_parameters=True, pool_pre_ping=True)
        validate_runtime_role(engine)
        sessions = sessionmaker(engine, expire_on_commit=False)
        storage = SupabaseFileStorage(settings.supabase_url, settings.supabase_storage_key, settings.supabase_storage_bucket)
        print('Authenticated both owners. Starting temporary loopback API and live checks.', flush=True)
        with live_server(create_app()) as base_url:
            clients = {label: httpx.Client(base_url=base_url, timeout=120, headers={'Authorization':'Bearer '+token}) for label, token in tokens.items()}
            LiveChecks(clients, owners, tokens, base_url, sessions, storage, report, save).run()
        report['status'] = 'verified'
        print('PASS: live HTTP scenarios verified. Physical cleanup/recovery apply remains separate.')
        return 0
    except Exception as exc:
        report['status'] = 'failed'
        report['failure_type'] = type(exc).__name__
        if isinstance(exc, VerificationFailure):
            report['failure'] = str(exc)
        raise
    finally:
        save()
        print('Sanitized report:', target.name)
        for client in clients.values():
            client.close()
        if storage:
            storage.close()
        if engine:
            engine.dispose()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as exc:
        print('STOP: live verification incomplete. No secrets displayed. Error type:', type(exc).__name__)
        raise SystemExit(1) from None
