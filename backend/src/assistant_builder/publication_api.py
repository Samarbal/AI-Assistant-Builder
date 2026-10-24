"""Authenticated owner-only publication and embed-snippet endpoints."""
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import CurrentOwner, OwnerContext
from .config import get_settings
from .db import get_db_session
from .publication import PublicationFailure, PublicationService

router = APIRouter(prefix="/assistants/{assistant_id}", tags=["publication"])


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_draft_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_published_version: int | None = Field(default=None, ge=1)


class PublicationRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    published: bool
    public_id: UUID | None
    version: int | None
    published_at: datetime | None
    draft_fingerprint: str
    has_changes: bool
    readiness: Literal["ready", "fallback_only", "needs_preparation", "processing", "failed"]


class PublishRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    public_id: UUID
    version: int
    published_at: str
    draft_fingerprint: str
    replayed: bool


class EmbedRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    public_id: UUID
    snippet: str


def get_publication_service(
    request: Request,
    session: Session = Depends(get_db_session, scope="function"),
) -> PublicationService:
    settings = get_settings()
    return PublicationService(
        session,
        embedding_provider=getattr(settings, "embedding_provider_name", "openai"),
        embedding_model=settings.embedding_model or "text-embedding-3-small",
        vector_dimension=settings.embedding_dimension,
        minimum_similarity=settings.retrieval_min_similarity,
    )


def _error(exc: PublicationFailure) -> HTTPException:
    status_code, message = {
        "not_found": (404, "Assistant not found."),
        "knowledge_not_ready": (409, "Knowledge must be ready before publishing."),
        "draft_changed": (409, "The draft changed. Refresh publication status and try again."),
        "publication_changed": (409, "The published version changed. Refresh and try again."),
        "idempotency_conflict": (409, "This idempotency key was already used for a different request."),
        "not_published": (409, "Publish this assistant before requesting its embed snippet."),
        "invalid_request": (422, "The publication request is invalid."),
        "publication_unavailable": (503, "Publication is temporarily unavailable."),
    }.get(exc.code, (503, "Publication is temporarily unavailable."))
    return HTTPException(status_code, detail={"code": exc.code, "message": message})


def _published_at(value) -> str:
    if value is None:
        raise PublicationFailure("publication_unavailable")
    return value.isoformat()


@router.get("/publication", response_model=PublicationRead)
def publication_status(
    assistant_id: UUID,
    response: Response,
    owner: OwnerContext = CurrentOwner,
    workflow: PublicationService = Depends(get_publication_service),
):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        return workflow.status(owner.owner_id, assistant_id)
    except PublicationFailure as exc:
        raise _error(exc) from None
    except SQLAlchemyError:
        raise HTTPException(503, detail={"code": "publication_unavailable",
            "message": "Publication status is temporarily unavailable."}) from None


@router.post("/publication", response_model=PublishRead)
def publish_assistant(
    assistant_id: UUID,
    payload: PublishRequest,
    response: Response,
    owner: OwnerContext = CurrentOwner,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    workflow: PublicationService = Depends(get_publication_service),
):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        publication, snapshot, replayed = workflow.publish(
            owner.owner_id, assistant_id,
            expected_fingerprint=payload.expected_draft_fingerprint,
            expected_version=payload.expected_published_version,
            idempotency_key=idempotency_key,
        )
        response.status_code = status.HTTP_200_OK if replayed else status.HTTP_201_CREATED
        return PublishRead(public_id=publication.public_id, version=snapshot.version,
            published_at=_published_at(snapshot.activated_at),
            draft_fingerprint=snapshot.draft_fingerprint, replayed=replayed)
    except PublicationFailure as exc:
        raise _error(exc) from None
    except SQLAlchemyError:
        raise HTTPException(503, detail={"code": "publication_unavailable",
            "message": "Publication could not be completed safely."}) from None


def _widget_origin(value: str | None) -> str:
    if not value:
        raise PublicationFailure("publication_unavailable")
    parsed = urlsplit(value)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    if (parsed.scheme != "https" and not local_http) or not parsed.hostname or parsed.username or parsed.password \
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise PublicationFailure("publication_unavailable")
    return f"{parsed.scheme}://{parsed.netloc}"


@router.get("/embed", response_model=EmbedRead)
def embed_snippet(
    assistant_id: UUID,
    response: Response,
    owner: OwnerContext = CurrentOwner,
    workflow: PublicationService = Depends(get_publication_service),
):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        publication = workflow.get_active_publication(owner.owner_id, assistant_id)
        origin = _widget_origin(get_settings().widget_asset_origin)
        public_id = str(publication.public_id)
        snippet = f'<script async src="{origin}/widget.js" data-assistant-id="{public_id}"></script>'
        return EmbedRead(public_id=publication.public_id, snippet=snippet)
    except PublicationFailure as exc:
        raise _error(exc) from None
    except SQLAlchemyError:
        raise HTTPException(503, detail={"code": "publication_unavailable",
            "message": "The embed snippet is temporarily unavailable."}) from None
