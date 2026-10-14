import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from assistant_builder.auth import OwnerContext, get_current_owner
from assistant_builder.config import get_settings
from assistant_builder.knowledge_api import service
from assistant_builder.knowledge_repository import KnowledgeNotFound
from assistant_builder.knowledge_service import KnowledgeNotReady
from assistant_builder.main import create_app
from assistant_builder.models import KnowledgeFile
from assistant_builder.storage import SupabaseFileStorage, StorageUnavailable
from .test_knowledge_upload import workflow, docx_bytes


def test_adapter_signs_exact_key_ttl_and_encodes_download_name():
    path = '/object/sign/knowledge-files/owners/abc/original.pdf'
    def handler(request):
        assert request.method == 'POST' and request.url.path == '/storage/v1' + path
        assert json.loads(request.content) == {'expiresIn': 60}
        return httpx.Response(200, json={'signedURL': path + '?token=test-only'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        storage = SupabaseFileStorage('https://example.supabase.co', 'test', 'knowledge-files', client)
        url = storage.signed_download_url('owners/abc/original.pdf', 'report & notes.pdf', 60)
        assert url == 'https://example.supabase.co/storage/v1' + path + '?token=test-only&download=report%20%26%20notes.pdf'


@pytest.mark.parametrize('payload', [None, {}, {'signedURL': None},
    {'signedURL': 'https://untrusted.example/file?token=x'},
    {'signedURL': '/object/sign/knowledge-files/other.pdf?token=x'},
    {'signedURL': '/object/sign/knowledge-files/file.pdf'},
    {'signedURL': '/object/sign/knowledge-files/file.pdf?download=1'},
])
def test_malformed_or_wrong_object_url_rejected(payload):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        storage = SupabaseFileStorage('https://example.supabase.co', 'test', 'knowledge-files', client)
        with pytest.raises(StorageUnavailable):
            storage.signed_download_url('file.pdf', 'file.pdf', 60)


@pytest.mark.parametrize('status', [400, 401, 404, 429, 500])
def test_signing_failure_hides_provider_response(status):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, text='private provider details'))) as client:
        storage = SupabaseFileStorage('https://example.supabase.co', 'test', 'knowledge-files', client)
        with pytest.raises(StorageUnavailable) as error:
            storage.signed_download_url('file.pdf', 'file.pdf', 60)
        assert not str(error.value)


def test_owner_file_parent_and_removed_checks_before_signing(workflow):
    flow, owner, assistant, _, _ = workflow
    item = flow.upload(owner, assistant, 'hours.docx', docx_bytes())
    calls = []
    flow.storage.signed_download_url = lambda *args: calls.append(args) or 'https://example.test/signed'
    assert flow.download_url(owner, assistant, item.id, 60).endswith('/signed')
    assert calls == [(item.object_key, 'hours.docx', 60)]
    for requested_owner, parent, file_id in [(uuid4(), assistant, item.id), (owner, uuid4(), item.id), (owner, assistant, uuid4())]:
        with pytest.raises(KnowledgeNotFound):
            flow.download_url(requested_owner, parent, file_id, 60)
    flow.remove(owner, assistant, item.id)
    with pytest.raises(KnowledgeNotFound):
        flow.download_url(owner, assistant, item.id, 60)
    assert len(calls) == 1


@pytest.mark.parametrize('state', ['accepted', 'processing', 'failed'])
def test_unfinished_or_failed_file_not_signed(workflow, state):
    flow, owner, assistant, sessions, _ = workflow
    item = flow.upload(owner, assistant, 'hours.docx', docx_bytes())
    with sessions.begin() as session:
        session.get(KnowledgeFile, item.id).processing_state = state
    # No signing method: any unexpected Storage call would fail this test.
    with pytest.raises(KnowledgeNotReady):
        flow.download_url(owner, assistant, item.id, 60)


def test_removal_during_signing_does_not_deliver_url(workflow):
    flow, owner, assistant, _, _ = workflow
    item = flow.upload(owner, assistant, 'hours.docx', docx_bytes())
    def sign(*args):
        flow.remove(owner, assistant, item.id)
        return 'https://example.test/not-delivered'
    flow.storage.signed_download_url = sign
    with pytest.raises(KnowledgeNotFound):
        flow.download_url(owner, assistant, item.id, 60)


def test_endpoint_auth_expiry_cache_headers_and_errors():
    app = create_app()
    owner, assistant, file_id = uuid4(), uuid4(), uuid4()
    calls = []
    def download(*args):
        calls.append(args)
        return 'https://example.test/signed'
    fake = SimpleNamespace(download_url=download)
    app.dependency_overrides[service] = lambda: fake
    path = f'/assistants/{assistant}/knowledge-files/{file_id}/download-url'
    with TestClient(app) as client:
        assert client.post(path).status_code == 401
        assert not calls
        app.dependency_overrides[get_current_owner] = lambda: OwnerContext(owner)
        response = client.post(path)
        assert response.status_code == 200 and response.json()['expires_in'] == 60
        assert response.headers['cache-control'] == 'no-store'
        assert calls == [(owner, assistant, file_id, 60)]
        get_settings().storage_signed_url_seconds = 30
        assert client.post(path, json={'owner_id': str(uuid4()), 'expires_in': 99999}).json()['expires_in'] == 30
        assert calls[-1] == (owner, assistant, file_id, 30)
        for exception, code in [(KnowledgeNotFound, 404), (KnowledgeNotReady, 409), (StorageUnavailable, 503)]:
            def fail(*args):
                raise exception()
            fake.download_url = fail
            response = client.post(path)
            assert response.status_code == code and 'download_url' not in response.json()
