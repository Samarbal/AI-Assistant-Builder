from fastapi import FastAPI
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from fastapi.responses import Response
from sqlalchemy.orm import sessionmaker
from .db import create_database_engine, validate_runtime_role

from .api import router as assistant_router
from .auth import SupabaseAuthVerifier
from .config import get_settings
from .knowledge_api import router as knowledge_router
from .playground_api import router as playground_router
from .publication_api import router as publication_router
from .indexing_api import router as indexing_router
from .public_api import router as public_router, configure_public_chat
from .conversation_history_api import router as conversation_history_router
from .chunking import DeterministicChunker, TiktokenTokenizer
from .embeddings import EmbeddingFailure, OpenAIEmbeddingProvider
from .generation import GenerationFailure, GroqAnswerGenerator
from .indexing import IndexingFailure, VersionedIndexService
from .rag import RagOrchestrator
from .retrieval import PgVectorRetriever, RetrievalFailure
from .storage import SupabaseFileStorage
from .upload_limit import UploadBodyLimit


def build_rag_orchestrator(session_factory, settings):
    """Compose providers only when all deployment configuration is present."""
    threshold = getattr(settings, "retrieval_min_similarity", None)
    if (session_factory is None or threshold is None
            or not getattr(settings, "embedding_api_key", None)
            or not getattr(settings, "embedding_base_url", None)
            or not getattr(settings, "embedding_model", None)
            or not getattr(settings, "ai_api_key", None)
            or not getattr(settings, "ai_base_url", None)
            or not getattr(settings, "ai_model", None)):
        return None
    try:
        embeddings = OpenAIEmbeddingProvider(settings)
        retriever = PgVectorRetriever(session_factory, embeddings,
            minimum_similarity=threshold,
            embedding_provider_name="openai", embedding_model=settings.embedding_model,
            dimension=settings.embedding_dimension)
        generator = GroqAnswerGenerator(settings)
        return RagOrchestrator(session_factory, retriever, generator)
    except (EmbeddingFailure, GenerationFailure, RetrievalFailure):
        return None


def build_indexing_service(session_factory, settings):
    """Compose the existing indexer without performing provider I/O at startup."""
    if (session_factory is None or not getattr(settings, "embedding_api_key", None)
            or not getattr(settings, "embedding_base_url", None)
            or not getattr(settings, "embedding_model", None)):
        return None
    try:
        tokenizer = TiktokenTokenizer()
        return VersionedIndexService(
            session_factory, DeterministicChunker(tokenizer),
            OpenAIEmbeddingProvider(settings), tokenizer=tokenizer,
            embedding_model=settings.embedding_model,
            vector_dimension=settings.embedding_dimension,
            embedding_provider_name="openai",
        )
    except (EmbeddingFailure, IndexingFailure):
        return None


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
            app.state.rag_orchestrator = build_rag_orchestrator(app.state.session_factory, settings)
            app.state.indexing_service = build_indexing_service(app.state.session_factory, settings)
            configure_public_chat(app, settings)
            app.state.file_storage = (
                SupabaseFileStorage(settings.supabase_url, settings.supabase_storage_key,
                                    settings.supabase_storage_bucket)
                if settings.supabase_url and settings.supabase_storage_key else None
            )
            yield
        finally:
            if engine is not None:
                engine.dispose()
            public_engine = getattr(app.state, "public_chat_engine", None)
            if public_engine is not None:
                public_engine.dispose()
            app.state.session_factory = None
            app.state.rag_orchestrator = None
            app.state.indexing_service = None
            app.state.public_chat_service = None
            storage = getattr(app.state, 'file_storage', None)
            if storage is not None:
                storage.close()
            verifier = getattr(app.state, "auth_verifier", None)
            if isinstance(verifier, SupabaseAuthVerifier):
                verifier.client.close()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    # Public widget CORS is deliberately narrower than app-wide CORS: only the
    # public-chat route family gets browser access, from the exact configured
    # widget asset origin. Owner APIs remain same-origin and unchanged.
    widget_origin = getattr(settings, "widget_asset_origin", None)
    if widget_origin:
        parsed = urlsplit(widget_origin)
        local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
        if (parsed.scheme != "https" and not local_http) or not parsed.hostname or parsed.username or parsed.password \
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or widget_origin == "*":
            raise ValueError("WIDGET_ASSET_ORIGIN must be one exact HTTPS origin (HTTP loopback is allowed for development)")
        widget_origin = f"{parsed.scheme}://{parsed.netloc}"

    @app.middleware("http")
    async def public_widget_cors(request, call_next):
        public_path = request.url.path.startswith("/public/assistants/")
        origin = request.headers.get("origin")
        if public_path and request.method == "OPTIONS" and request.headers.get("access-control-request-method"):
            if not widget_origin or origin != widget_origin:
                return Response(status_code=403)
            requested_method = request.headers.get("access-control-request-method", "").upper()
            requested_headers = {item.strip().lower() for item in request.headers.get(
                "access-control-request-headers", "").split(",") if item.strip()}
            allowed_headers = {"content-type", "x-demo-access", "x-visitor-token"}
            if requested_method not in {"GET", "POST"} or not requested_headers.issubset(allowed_headers):
                return Response(status_code=403)
            return Response(status_code=204, headers={
                "Access-Control-Allow-Origin": widget_origin,
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, X-Demo-Access, X-Visitor-Token",
                "Access-Control-Max-Age": "300",
                "Vary": "Origin",
            })
        response = await call_next(request)
        if public_path and origin and widget_origin and origin == widget_origin:
            response.headers["Access-Control-Allow-Origin"] = widget_origin
            response.headers["Vary"] = "Origin"
        return response

    if settings.supabase_url and settings.supabase_anon_key:
        app.state.auth_verifier = SupabaseAuthVerifier(settings.supabase_url, settings.supabase_anon_key)
    app.include_router(assistant_router)
    app.include_router(knowledge_router)
    app.include_router(playground_router)
    app.include_router(publication_router)
    app.include_router(indexing_router)
    app.include_router(public_router)
    app.include_router(conversation_history_router)
    app.add_middleware(UploadBodyLimit)
    return app


app = create_app()
