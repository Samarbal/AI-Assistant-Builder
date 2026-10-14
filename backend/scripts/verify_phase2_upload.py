"""Interactive real Supabase Auth -> FastAPI -> private Storage -> PostgreSQL check.

Retains one clearly named test assistant and document for owner inspection. Never
saves passwords or tokens. Does not use migration credentials or delete data.
"""
import getpass
from hashlib import sha256
from io import BytesIO
import json
import logging
from pathlib import Path
import sys
import warnings
from uuid import UUID, uuid4

import httpx
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select

from assistant_builder.auth import SupabaseAuthVerifier
from assistant_builder.config import Settings
from assistant_builder.db import set_owner_identity
from assistant_builder.main import create_app
from assistant_builder.models import KnowledgeFile, KnowledgeFileText
from signin_phase1 import sign_in, validate_auth_settings


def main():
    logging.disable(logging.CRITICAL)
    warnings.filterwarnings('error', category=getpass.GetPassWarning)
    settings = Settings()
    validate_auth_settings(settings)
    if not settings.supabase_storage_key:
        print('BLOCKED: set SUPABASE_STORAGE_KEY locally first')
        return 2
    if not sys.stdin.isatty():
        print('BLOCKED: run in an interactive terminal for hidden password entry')
        return 2
    report = {'status': 'incomplete', 'passed': [], 'retained_assistant_id': None, 'retained_file_id': None}
    report_path = Path('../docs/ai-sdlc/contracts/PHASE-2-UPLOAD-LIVE-RESULTS.json')
    try:
        email = input('Test owner email: ').strip()
        password = getpass.getpass('Test owner password (hidden): ')
        with httpx.Client(timeout=20) as client:
            token = sign_in(client, settings.supabase_url, settings.supabase_anon_key, email, password)
            del email, password
            owner = SupabaseAuthVerifier(settings.supabase_url, settings.supabase_anon_key, client).verify('Bearer ' + token)
        headers = {'Authorization': 'Bearer ' + token}
        document = Document()
        fixture_text = 'Phase 2 upload verification: opening hours are nine to five.'
        document.add_paragraph(fixture_text)
        stream = BytesIO()
        document.save(stream)
        content = stream.getvalue()
        app = create_app()
        with TestClient(app) as client:
            response = client.post('/assistants', headers=headers, json={
                'name': 'Phase 2 upload check ' + str(uuid4())[:8], 'role': 'Customer support',
                'colors': {}, 'response_style': 'Concise', 'tone': 'Friendly', 'fallback_message': 'I cannot find that answer.'})
            assert response.status_code == 201, 'Assistant creation failed'
            assistant = response.json()['id']
            report['retained_assistant_id'] = assistant
            response = client.post(f'/assistants/{assistant}/knowledge-files', headers=headers,
                files={'file': ('phase2-check.docx', content, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
            assert response.status_code == 201, 'Upload failed'
            file_id = UUID(response.json()['id'])
            report['retained_file_id'] = str(file_id)
            assert response.json()['processing_state'] == 'extracted'
            report['passed'].append('Real Supabase owner authenticated; FastAPI multipart upload returned 201/extracted')
            with app.state.session_factory.begin() as session:
                set_owner_identity(session, owner.owner_id)
                item = session.get(KnowledgeFile, file_id)
                assert item is not None and item.owner_id == owner.owner_id
                assert item.content_sha256 == sha256(content).hexdigest()
                assert fixture_text in session.scalar(select(KnowledgeFileText.extracted_text).where(KnowledgeFileText.file_id == file_id))
                object_key = item.object_key
            report['passed'].append('Metadata and extracted DOCX text committed through restricted runtime connection')
            storage = app.state.file_storage
            object_path = f'/object/{storage.bucket}/{object_key}'
            downloaded = storage.client.get(storage.base_url + object_path)
            assert downloaded.status_code == 200 and sha256(downloaded.content).digest() == sha256(content).digest()
            bucket = storage.client.get(f'{storage.base_url}/bucket/{storage.bucket}')
            assert bucket.status_code == 200 and bucket.json()['public'] is False
            with httpx.Client(timeout=20) as public:
                anonymous = public.get(storage.base_url + '/object/public/' + storage.bucket + '/' + object_key)
                assert anonymous.status_code in (400, 401, 403, 404)
                direct = public.get(storage.base_url + '/object/authenticated/' + storage.bucket + '/' + object_key,
                    headers={**headers, 'apikey': settings.supabase_anon_key})
                assert direct.status_code in (400, 401, 403, 404)
            report['passed'].append('Private stored bytes match; public and direct owner Storage downloads denied')
            listing = client.get(f'/assistants/{assistant}/knowledge-files', headers=headers)
            assert listing.status_code == 200 and any(f['id'] == str(file_id) for f in listing.json())
            report['passed'].append('Owner can list the uploaded attachment')
            signed = client.post(f'/assistants/{assistant}/knowledge-files/{file_id}/download-url', headers=headers)
            assert signed.status_code == 200 and signed.headers['cache-control'] == 'no-store'
            assert signed.json()['expires_in'] == settings.storage_signed_url_seconds
            with httpx.Client(timeout=20) as downloader:
                download = downloader.get(signed.json()['download_url'])
                assert download.status_code == 200 and sha256(download.content).digest() == sha256(content).digest()
                assert 'attachment' in download.headers.get('content-disposition', '')
            report['passed'].append('Authenticated download endpoint issued configured signed URL; downloaded bytes match')
        report['status'] = 'verified'
        for result in report['passed']:
            print('PASS:', result)
        print('Verification succeeded. One test assistant/document retained for inspection; IDs are in the report.')
        return 0
    finally:
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as exc:
        print('STOP: upload verification failed. No secrets displayed. Error type:', type(exc).__name__)
        raise SystemExit(1) from None
