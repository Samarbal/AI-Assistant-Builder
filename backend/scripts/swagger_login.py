"""Windows local sign-in: place a short-lived user token on clipboard, never print it."""
import getpass
import logging
import subprocess
import sys
import warnings
import httpx
from assistant_builder.config import Settings
from assistant_builder.auth import SupabaseAuthVerifier
from signin_phase1 import sign_in, validate_auth_settings


def main():
    logging.disable(logging.CRITICAL)
    warnings.filterwarnings('error', category=getpass.GetPassWarning)
    if sys.platform != 'win32' or not sys.stdin.isatty():
        raise RuntimeError('Interactive Windows terminal required')
    settings = Settings()
    validate_auth_settings(settings)
    email = input('Owner email: ').strip()
    password = getpass.getpass('Owner password (hidden): ')
    with httpx.Client(timeout=20) as client:
        token = sign_in(client, settings.supabase_url, settings.supabase_anon_key, email, password)
        del email, password
        SupabaseAuthVerifier(settings.supabase_url, settings.supabase_anon_key, client).verify('Bearer ' + token)
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', '$input | Set-Clipboard'],
        input=token, text=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW)
    print('User access token copied locally. Paste into Swagger Authorize (without Bearer).')
    print('Do not share the clipboard. Clear it after pasting: Set-Clipboard -Value ""')


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt):
        print('STOP: sign-in/clipboard failed. No secrets displayed.')
        raise SystemExit(1) from None
