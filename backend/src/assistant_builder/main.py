from fastapi import FastAPI
from contextlib import asynccontextmanager
from sqlalchemy.orm import sessionmaker
from .db import create_database_engine, validate_runtime_role

from .api import router as assistant_router
from .auth import SupabaseAuthVerifier
from .config import get_settings
from .knowledge_api import router as knowledge_router
from .storage import SupabaseFileStorage
from .upload_limit import UploadBodyLimit


def create_app() -> FastAPI:
    settings = get_settings()
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_database_engine() if settings.database_url else None
        try:
            if engine is not None:
                validate_runtime_role(engine)
            app.state.session_factory = (
                sessionmaker(engine, autoflush=False, expire_on_commit=False) if engine else None
            )
            app.state.file_storage = (
                SupabaseFileStorage(settings.supabase_url, settings.supabase_storage_key,
                                    settings.supabase_storage_bucket)
                if settings.supabase_url and settings.supabase_storage_key else None
            )
            yield
        finally:
            if engine is not None:
                engine.dispose()
            app.state.session_factory = None
            storage = getattr(app.state, 'file_storage', None)
            if storage is not None:
                storage.close()
            verifier = getattr(app.state, "auth_verifier", None)
            if isinstance(verifier, SupabaseAuthVerifier):
                verifier.client.close()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    if settings.supabase_url and settings.supabase_anon_key:
        app.state.auth_verifier = SupabaseAuthVerifier(settings.supabase_url, settings.supabase_anon_key)
    app.include_router(assistant_router)
    app.include_router(knowledge_router)
    app.add_middleware(UploadBodyLimit)
    return app


app = create_app()
