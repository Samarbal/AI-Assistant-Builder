from fastapi import FastAPI

from .api import router as assistant_router
from .auth import SupabaseAuthVerifier
from .config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    if settings.supabase_url and settings.supabase_anon_key:
        app.state.auth_verifier = SupabaseAuthVerifier(settings.supabase_url, settings.supabase_anon_key)
    app.include_router(assistant_router)
    return app


app = create_app()
