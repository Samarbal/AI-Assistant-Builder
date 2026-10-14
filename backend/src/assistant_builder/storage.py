"""Server-only Storage boundary. Callers must authorize the stored object identity."""
from typing import Protocol
from urllib.parse import quote, urlparse, urlsplit, parse_qs

import httpx

MIME_TYPES = {'pdf': 'application/pdf', 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


class StorageUnavailable(Exception):
    pass


class FileStorage(Protocol):
    def upload(self, key: str, content: bytes, file_format: str) -> None: ...
    def signed_download_url(self, key: str, filename: str, expires_in: int) -> str: ...


class MaintenanceStorage(Protocol):
    def remove_recorded_object(self, key: str) -> None: ...


class SupabaseFileStorage:
    def __init__(self, url: str, secret: str, bucket: str, client=None):
        if urlparse(url).scheme != 'https' or not bucket or '/' in bucket:
            raise ValueError('HTTPS Storage configuration required')
        self.base_url = url.rstrip('/') + '/storage/v1'
        self.bucket = bucket
        headers = {'apikey': secret}
        if not secret.startswith('sb_secret_'):
            headers['Authorization'] = 'Bearer ' + secret
        self.client = client or httpx.Client(headers=headers, timeout=30)

    def upload(self, key, content, file_format):
        try:
            response = self.client.post(
                f'{self.base_url}/object/{quote(self.bucket, safe="")}/{quote(key, safe="/")}',
                content=content, headers={'Content-Type': MIME_TYPES[file_format], 'x-upsert': 'false'})
            if response.status_code not in (200, 201):
                raise StorageUnavailable()
        except httpx.RequestError:
            raise StorageUnavailable() from None

    def signed_download_url(self, key, filename, expires_in):
        if not 1 <= expires_in <= 300:
            raise ValueError('Signed download lifetime must be between 1 and 300 seconds')
        path = f'/object/sign/{quote(self.bucket, safe="")}/{quote(key, safe="/")}'
        try:
            response = self.client.post(self.base_url + path, json={'expiresIn': expires_in})
            if response.status_code != 200:
                raise StorageUnavailable()
            signed = response.json()['signedURL']
            parsed = urlsplit(signed)
            # Accept only a provider-relative URL for the exact authorized object.
            tokens = parse_qs(parsed.query).get('token', [])
            if (parsed.scheme or parsed.netloc or parsed.path != path or parsed.fragment
                    or len(tokens) != 1 or not tokens[0]):
                raise StorageUnavailable()
            return self.base_url + signed + '&download=' + quote(filename, safe='')
        except (httpx.RequestError, ValueError, KeyError, TypeError, AttributeError):
            raise StorageUnavailable() from None

    def remove_recorded_object(self, key):
        """Operator-only exact-key delete; never list a bucket or delete a prefix."""
        try:
            response = self.client.request('DELETE',
                f'{self.base_url}/object/{quote(self.bucket, safe="")}', json={'prefixes': [key]})
            # Supabase returns [] for an already absent object. A 404/403 may
            # instead mean a missing bucket or broken authorization: do not hide it.
            if response.status_code != 200:
                raise StorageUnavailable()
            removed = response.json()
            if not isinstance(removed, list) or any(
                    not isinstance(item, dict) or item.get('name') != key for item in removed):
                raise StorageUnavailable()
        except (httpx.RequestError, ValueError, TypeError):
            raise StorageUnavailable() from None

    def close(self):
        self.client.close()
