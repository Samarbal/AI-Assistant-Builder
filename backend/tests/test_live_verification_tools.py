"""Safety checks for interactive sign-in and narrowly scoped fixture cleanup."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from signin_phase1 import sign_in, validate_auth_settings, SafeSetupError
from types import SimpleNamespace
from verify_phase1_live import cleanup_fixtures


@pytest.mark.parametrize('url,key,expected', [
    (None, None, 'SUPABASE_URL'),
    ('https://auth.example', None, 'SUPABASE_ANON_KEY'),
    ('https://user:secret@auth.example', 'private-value', 'HTTPS project URL'),
    ('https://[invalid', 'private-value', 'HTTPS project URL'),
])
def test_setup_errors_are_actionable_without_exposing_values(url, key, expected):
    with pytest.raises(SafeSetupError) as error:
        validate_auth_settings(SimpleNamespace(supabase_url=url, supabase_anon_key=key))
    assert expected in str(error.value)
    assert 'private-value' not in str(error.value)
    assert 'user:secret' not in str(error.value)


def test_valid_auth_configuration():
    validate_auth_settings(SimpleNamespace(supabase_url='https://auth.example', supabase_anon_key='test-key'))


def test_password_signin_uses_auth_endpoint_without_output(capsys):
    def handler(request):
        assert request.url.path == '/auth/v1/token'
        assert request.url.params['grant_type'] == 'password'
        assert request.headers['apikey'] == 'test-key'
        return httpx.Response(200, json={'access_token': 'test-token'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert sign_in(client, 'https://auth.example', 'test-key', 'test@example.com', 'test-password') == 'test-token'
    assert capsys.readouterr() == ('', '')


def test_signin_failure_does_not_include_server_response():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(400, text='sensitive-response'))) as client:
        with pytest.raises(RuntimeError) as error:
            sign_in(client, 'https://auth.example', 'test-key', 'test@example.com', 'test-password')
    assert 'sensitive-response' not in str(error.value)
    assert 'test-password' not in str(error.value)


def test_cleanup_refuses_dependencies_before_delete():
    admin = MagicMock()
    connection = admin.begin.return_value.__enter__.return_value
    connection.scalar.return_value = True
    with pytest.raises(RuntimeError):
        cleanup_fixtures(admin, [{'id': 'fixture', 'owner': 'owner', 'role': 'marker'}])
    assert not any('DELETE' in str(call.args[0]) for call in connection.execute.call_args_list)
    assert admin.begin.return_value.__exit__.call_args.args[0] is RuntimeError


def test_cleanup_refuses_mismatched_owner_before_delete():
    admin = MagicMock()
    connection = admin.begin.return_value.__enter__.return_value
    connection.scalar.return_value = False
    connection.execute.return_value.one.return_value = type('Row', (), {'owner_id': 'other', 'role': 'marker', 'state': 'draft'})()
    with pytest.raises(RuntimeError):
        cleanup_fixtures(admin, [{'id': 'fixture', 'owner': 'owner', 'role': 'marker'}])
    assert not any('DELETE' in str(call.args[0]) for call in connection.execute.call_args_list)


def test_cleanup_uses_exact_fixture_predicate_and_requires_one_row():
    admin = MagicMock()
    connection = admin.begin.return_value.__enter__.return_value
    connection.scalar.return_value = False
    connection.execute.return_value.one.return_value = type('Row', (), {'owner_id': 'owner', 'role': 'marker', 'state': 'draft'})()
    connection.execute.return_value.rowcount = 0
    fixture = {'id': 'fixture', 'owner': 'owner', 'role': 'marker'}
    with pytest.raises(RuntimeError):
        cleanup_fixtures(admin, [fixture])
    deletion = connection.execute.call_args
    assert 'id=:id AND owner_id=:owner AND role=:role' in str(deletion.args[0])
    assert deletion.args[1] == fixture
    assert admin.begin.return_value.__exit__.call_args.args[0] is RuntimeError
