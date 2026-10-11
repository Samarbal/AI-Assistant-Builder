"""Interactive local sign-in; credentials and tokens stay in this process only."""
import getpass
import logging
import sys
import warnings
from urllib.parse import urlsplit

import httpx

from assistant_builder.auth import SupabaseAuthVerifier
from assistant_builder.config import Settings
from verify_phase1_live import main as verify


class SafeSetupError(RuntimeError):
    """Only developer-written messages without external response/config values."""


def validate_auth_settings(settings):
    if not settings.supabase_url:
        raise SafeSetupError('Set SUPABASE_URL in backend/.env (HTTPS project URL).')
    try:
        url = urlsplit(settings.supabase_url)
        valid = url.scheme == 'https' and url.hostname and not (url.username or url.password or url.query or url.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise SafeSetupError('SUPABASE_URL must be an HTTPS project URL without credentials, query or fragment.')
    if not settings.supabase_anon_key:
        raise SafeSetupError('Set SUPABASE_ANON_KEY in backend/.env to the project publishable or legacy anon key, not a service-role/secret key.')


def sign_in(client, base_url, api_key, email, password):
    response = client.post(
        base_url.rstrip('/') + '/auth/v1/token',
        params={'grant_type': 'password'},
        headers={'apikey': api_key},
        json={'email': email, 'password': password},
    )
    if response.status_code != 200:
        raise RuntimeError('Sign-in failed; check credentials and email confirmation locally')
    token = response.json().get('access_token')
    if not isinstance(token, str) or not token:
        raise RuntimeError('Sign-in returned no access token')
    return token


def main():
    logging.disable(logging.CRITICAL)
    warnings.filterwarnings('error', category=getpass.GetPassWarning)
    if not sys.stdin.isatty():
        raise SafeSetupError('Run in your own interactive terminal; hidden input is required (no pipes).')
    settings = Settings()
    validate_auth_settings(settings)
    tokens = []
    owners = []
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        verifier = SupabaseAuthVerifier(settings.supabase_url, settings.supabase_anon_key, client=client)
        for label in ('A', 'B'):
            email = input(f'Test user {label} email: ').strip()
            print('Password input is hidden (no characters or stars). Type or paste it, then press Enter.')
            password = getpass.getpass(f'Test user {label} password (hidden): ')
            token = sign_in(client, settings.supabase_url, settings.supabase_anon_key, email, password)
            del email, password
            owners.append(verifier.verify('Bearer ' + token).owner_id)
            tokens.append(token)
        if owners[0] == owners[1]:
            raise RuntimeError('Two different authenticated test users are required')
    print('Both test users authenticated. Starting live verification; no tokens saved.')
    verify(tokens=tokens, cleanup=True)


if __name__ == '__main__':
    try:
        main()
    except SafeSetupError as exc:
        print('STOP:', str(exc))
        raise SystemExit(1) from None
    except (Exception, KeyboardInterrupt):
        # Do not print HTTP exceptions, response bodies, credentials or tracebacks.
        print('STOP: sign-in or verification failed. No secrets displayed; review the sanitized report if verification started.')
        raise SystemExit(1) from None
