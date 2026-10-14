"""Configure the approved private bucket only; never change global Storage policies."""
import logging
from sqlalchemy import create_engine, text
from assistant_builder.config import Settings, MigrationSettings
from assistant_builder.storage import SupabaseFileStorage, MIME_TYPES


def main():
    settings = Settings()
    if not settings.supabase_storage_key:
        print('BLOCKED: set SUPABASE_STORAGE_KEY locally in backend/.env')
        return 2
    engine = create_engine(MigrationSettings().migration_database_url, hide_parameters=True)
    with engine.connect() as connection:
        connection.execute(text('SET TRANSACTION READ ONLY'))
        # Any existing policy needs targeted review; a private bucket alone does
        # not deny authenticated API requests covered by broad Storage policies.
        assert connection.scalar(text("SELECT count(*) FROM pg_policies WHERE schemaname='storage' AND tablename='objects'")) == 0, 'Storage policies require review'
    engine.dispose()
    storage = SupabaseFileStorage(settings.supabase_url, settings.supabase_storage_key, settings.supabase_storage_bucket)
    try:
        endpoint = storage.base_url + '/bucket/' + storage.bucket
        response = storage.client.get(endpoint)
        if response.status_code in (400, 404):
            # Verify absence by list; never treat an arbitrary 400 as not-found.
            listing = storage.client.get(storage.base_url + '/bucket')
            assert listing.status_code == 200 and isinstance(listing.json(), list)
            assert all(b['id'] != storage.bucket for b in listing.json())
            created = storage.client.post(storage.base_url + '/bucket', json={
                'id': storage.bucket, 'name': storage.bucket, 'public': False,
                'file_size_limit': 10_000_000, 'allowed_mime_types': list(MIME_TYPES.values())})
            assert created.status_code in (200, 201), 'Bucket creation failed'
            response = storage.client.get(endpoint)
        assert response.status_code == 200
        bucket = response.json()
        assert bucket['public'] is False
        assert bucket['file_size_limit'] == 10_000_000
        assert set(bucket['allowed_mime_types']) == set(MIME_TYPES.values())
        print('PASS: private knowledge-files bucket, 10 MB/PDF/DOCX limits, no client Storage policies')
    finally:
        storage.close()
    return 0


if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('STOP: Storage setup failed; no policy changes made. Error type:', type(exc).__name__)
        raise SystemExit(1) from None
