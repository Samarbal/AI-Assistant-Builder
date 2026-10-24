"""Demo-gated public assistant/conversation/message API. No widget assets here."""
from datetime import datetime
import asyncio
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictStr, StringConstraints
from sqlalchemy.orm import sessionmaker

from .config import get_settings
from .db import create_public_database_engine, validate_public_runtime_role
from .embeddings import OpenAIEmbeddingProvider
from .generation import GroqAnswerGenerator
from .public_chat import PublicChatFailure, PublicChatService, PublicDemoGate, PublicRequestGuard

router = APIRouter(prefix="/public/assistants/{public_id}", tags=["public-chat"])
PublicMessageText = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateConversationRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    conversation_id: UUID
    conversation_token: str = Field(min_length=32, max_length=128)
    expires_at: datetime


class PublicAssistantRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(max_length=120)
    colors: dict[str, str]
    version: int = Field(ge=1)


class PublicMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: PublicMessageText
    request_id: UUID = Field(strict=False)


class PublicMessageRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message_id: UUID
    answer: str = Field(max_length=4000)
    outcome: Literal["grounded", "fallback"]
    created_at: datetime
    version: int = Field(ge=1)


def _public_service(request: Request) -> PublicChatService:
    service = getattr(request.app.state, "public_chat_service", None)
    if service is None:
        raise HTTPException(503, detail={"code": "public_chat_disabled", "message": "Public chat is unavailable."})
    return service


def _gate(request: Request, access_token: str | None) -> None:
    gate = getattr(request.app.state, "public_demo_gate", None)
    if gate is None:
        raise HTTPException(503, detail={"code": "public_chat_disabled", "message": "Public chat is unavailable."})
    try:
        gate.check(access_token)
    except PublicChatFailure as exc:
        code = "demo_access_denied" if exc.code == "demo_access_denied" else "public_chat_disabled"
        raise HTTPException(404 if code == "demo_access_denied" else 503,
            detail={"code": code, "message": "Public chat is unavailable."}) from None


async def _rate(request: Request, service: PublicChatService, public_id: UUID):
    # Never trust X-Forwarded-For / Forwarded without an explicitly configured proxy.
    ip = request.client.host if request.client else "unknown"
    try:
        await service.guard.check_rate(ip, public_id)
    except PublicChatFailure:
        raise HTTPException(429, detail={"code": "rate_limited", "message": "Please wait before trying again."}) from None


def _error(exc: PublicChatFailure) -> HTTPException:
    mapping = {
        "assistant_unavailable": (404, "assistant_unavailable"),
        "conversation_unavailable": (404, "conversation_unavailable"),
        "demo_access_denied": (404, "public_unavailable"),
        "invalid_request": (422, "invalid_request"),
        "request_in_progress": (409, "request_in_progress"),
        "request_conflict": (409, "request_conflict"),
        "published_version_changed": (409, "published_version_changed"),
        "concurrency_limited": (429, "rate_limited"),
        "rate_limited": (429, "rate_limited"),
        "public_chat_disabled": (503, "public_chat_disabled"),
        "knowledge_not_ready": (503, "public_unavailable"),
        "public_timeout": (503, "public_unavailable"),
        "public_provider_failure": (503, "public_unavailable"),
        "public_unavailable": (503, "public_unavailable"),
    }
    code_status, code = mapping.get(exc.code, (503, "public_unavailable"))
    return HTTPException(code_status, detail={"code": code, "message": "The assistant could not complete this request."})


@router.get("", response_model=PublicAssistantRead)
async def public_assistant(public_id: UUID, request: Request, response: Response,
                           x_demo_access: Annotated[str | None, Header(alias="X-Demo-Access", max_length=512)] = None):
    _gate(request, x_demo_access)
    service = _public_service(request)
    await _rate(request, service, public_id)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        return service.public_details(public_id)
    except PublicChatFailure as exc:
        raise _error(exc) from None


@router.post("/conversations", response_model=CreateConversationRead, status_code=201)
async def create_conversation(public_id: UUID, payload: EmptyRequest, request: Request, response: Response,
                              x_demo_access: Annotated[str | None, Header(alias="X-Demo-Access", max_length=512)] = None):
    _gate(request, x_demo_access)
    service = _public_service(request)
    await _rate(request, service, public_id)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        return service.create_conversation(public_id)
    except PublicChatFailure as exc:
        raise _error(exc) from None


@router.post("/conversations/{conversation_id}/messages", response_model=PublicMessageRead)
async def send_public_message(public_id: UUID, conversation_id: UUID, payload: PublicMessageRequest,
                              request: Request, response: Response,
                              x_visitor_token: Annotated[str | None, Header(alias="X-Visitor-Token", max_length=256)] = None,
                              x_demo_access: Annotated[str | None, Header(alias="X-Demo-Access", max_length=512)] = None):
    _gate(request, x_demo_access)
    service = _public_service(request)
    await _rate(request, service, public_id)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        async with asyncio.timeout(30):
            return await service.message(public_id, conversation_id, x_visitor_token or "",
                                         payload.message, payload.request_id)
    except TimeoutError:
        raise HTTPException(503, detail={"code": "public_unavailable",
            "message": "The assistant could not complete this request."}) from None
    except PublicChatFailure as exc:
        raise _error(exc) from None


def configure_public_chat(app, settings) -> None:
    """Called during lifespan. Disabled by default and no role/config fallback."""
    enabled = getattr(settings, "public_chat_enabled", False)
    demo_hashes = getattr(settings, "public_demo_token_sha256", None)
    app.state.public_demo_gate = PublicDemoGate(enabled, demo_hashes)
    app.state.public_chat_service = None
    if not enabled:
        return
    if not demo_hashes:
        raise RuntimeError("PUBLIC_DEMO_TOKEN_SHA256 is required when public chat is enabled")
    engine = create_public_database_engine()
    try:
        validate_public_runtime_role(engine)
        if not all((settings.embedding_api_key, settings.embedding_model, settings.ai_api_key, settings.ai_model)):
            raise RuntimeError("Public chat provider configuration is incomplete")
        sessions = sessionmaker(engine, autoflush=False, expire_on_commit=False)
        embeddings = OpenAIEmbeddingProvider(settings)
        generator = GroqAnswerGenerator(settings)
        app.state.public_chat_engine = engine
        app.state.public_chat_service = PublicChatService(sessions, embeddings, generator,
            PublicRequestGuard(rate=settings.public_rate_limit_per_minute,
                per_assistant=settings.public_max_concurrent,
                global_limit=settings.public_global_max_concurrent,
                key_capacity=settings.public_rate_key_capacity))
    except Exception:
        engine.dispose()
        raise
