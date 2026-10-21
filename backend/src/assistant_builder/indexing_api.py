"""Authenticated, bounded knowledge-index preparation routes."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from .auth import CurrentOwner, OwnerContext
from .indexing import IndexingFailure, PreparationStatus, VersionedIndexService

router = APIRouter(prefix="/assistants/{assistant_id}/playground", tags=["knowledge preparation"])


class PrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID | None = None


class PreparationRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    readiness: Literal["no_knowledge", "needs_preparation", "preparing", "ready", "failed", "blocked"]
    operation_id: UUID | None
    completed_chunks: int = Field(ge=0)
    total_chunks: int = Field(ge=0)
    eligible_files: int = Field(ge=0, le=5)
    next_action: Literal["prepare", "continue", "retry"] | None
    reason: str | None


def get_indexing_service(request: Request) -> VersionedIndexService:
    service = getattr(request.app.state, "indexing_service", None)
    if service is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail={
            "code": "indexing_unavailable", "message": "Knowledge preparation is not configured."
        })
    return service


def _read(value: PreparationStatus) -> PreparationRead:
    action = {
        "needs_preparation": "prepare",
        "preparing": "continue",
        "failed": "retry",
    }.get(value.state)
    if value.error_code == "provider_attempt_uncertain":
        action = None
    safe_reasons = {
        "file_processing": "Files are still being processed.",
        "extracted_text_unavailable": "One or more extracted text records are unavailable.",
        "source_changed": "The attached knowledge changed. Prepare the current files.",
        "embedding_provider_failure": "An embedding batch failed. Review status before retrying.",
        "embedding_invalid_output": "An embedding batch could not be validated.",
        "provider_attempt_uncertain": "A provider attempt needs operator review before retrying.",
        "index_cost_limit": "The estimated cost exceeds the allowed limit.",
        "index_resource_limit": "The current files exceed preparation limits.",
        "source_chunking_failure": "The extracted text could not be prepared safely.",
    }
    return PreparationRead(
        readiness=value.state,
        operation_id=value.operation_id,
        completed_chunks=value.completed_chunks,
        total_chunks=value.total_chunks,
        eligible_files=value.eligible_files,
        next_action=action,
        reason=safe_reasons.get(value.error_code or "", "Preparation needs attention." if value.state == "failed" else None),
    )


def _failure(exc: IndexingFailure) -> HTTPException:
    code = exc.code
    known = {
        "assistant_not_found": (404, "Assistant not found."),
        "index_not_found": (404, "Preparation operation not found."),
        "knowledge_not_ready": (409, "Wait for file processing to finish, then refresh status."),
        "preparation_busy": (409, "Preparation is already in progress. Refresh its status."),
        "preparation_request_already_used": (409, "This preparation request was already used. Refresh status before continuing."),
        "provider_attempt_uncertain": (409, "A previous embedding attempt needs operator review before preparation can continue."),
        "no_knowledge": (409, "Add a successfully extracted PDF or DOCX before preparing knowledge."),
        "index_resource_limit": (409, "This knowledge set exceeds the current preparation limits."),
        "index_cost_limit": (429, "The estimated embedding cost exceeds the per-index limit."),
        "source_chunking_failure": (422, "The extracted knowledge could not be prepared safely."),
        "index_input_limit": (422, "A knowledge chunk exceeds the supported preparation limit."),
        "index_invalid_request": (422, "The preparation request is invalid."),
        "index_lease_expired": (409, "This preparation lease expired. Refresh status before continuing."),
        "index_operation_fenced": (409, "This preparation operation changed. Refresh status before continuing."),
        "embedding_provider_failure": (503, "The embedding service could not complete this batch. Review status before retrying."),
        "embedding_invalid_output": (503, "The embedding service returned an invalid batch. Review status before retrying."),
        "index_configuration": (503, "Knowledge preparation is not configured correctly."),
        "index_chunk_manifest_invalid": (503, "The preparation manifest is unavailable. Contact the workspace operator."),
    }
    http_status, message = known.get(code, (503, "Knowledge preparation is temporarily unavailable."))
    safe_code = code if code in known else "indexing_unavailable"
    return HTTPException(http_status, detail={"code": safe_code, "message": message})


@router.get("/status", response_model=PreparationRead)
async def preparation_status(assistant_id: UUID, response: Response,
                       owner: OwnerContext = CurrentOwner,
                       workflow: VersionedIndexService = Depends(get_indexing_service)):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        current = await run_in_threadpool(workflow.status, owner.owner_id, assistant_id)
        result = _read(current)
        return result
    except IndexingFailure as exc:
        raise _failure(exc) from None
    except SQLAlchemyError:
        raise HTTPException(503, detail={"code": "indexing_unavailable",
            "message": "Knowledge preparation status is temporarily unavailable."}) from None


@router.post("/prepare", response_model=PreparationRead)
async def prepare_knowledge(assistant_id: UUID, payload: PrepareRequest, response: Response,
                            owner: OwnerContext = CurrentOwner,
                            idempotency_key: UUID = Header(alias="Idempotency-Key"),
                            workflow: VersionedIndexService = Depends(get_indexing_service)):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        if payload.operation_id is None:
            started = await run_in_threadpool(
                workflow.start, owner.owner_id, assistant_id, idempotency_key)
            index_id = started.index_id
            if started.state == "building":
                await workflow.advance(owner.owner_id, assistant_id, index_id,
                                       idempotency_key=idempotency_key)
        else:
            index_id = payload.operation_id
            await workflow.advance(owner.owner_id, assistant_id, index_id,
                                   idempotency_key=idempotency_key)
        current = await run_in_threadpool(workflow.status, owner.owner_id, assistant_id)
        result = _read(current)
        if result.readiness == "preparing":
            response.status_code = status.HTTP_202_ACCEPTED
        return result
    except IndexingFailure as exc:
        raise _failure(exc) from None
    except SQLAlchemyError:
        raise HTTPException(503, detail={"code": "indexing_unavailable",
            "message": "Knowledge preparation is temporarily unavailable. Refresh status before retrying."}) from None
