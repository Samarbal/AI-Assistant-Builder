"""Authenticated one-turn Playground API. No visitor/public access or persistence."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr, StringConstraints

from .auth import CurrentOwner, OwnerContext
from .rag import RagFailure, RagOrchestrator

router = APIRouter(prefix="/assistants/{assistant_id}/playground", tags=["playground"])

PlaygroundText = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class PlaygroundMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: PlaygroundText


class PlaygroundCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    file_id: UUID
    chunk_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    excerpt: str = Field(min_length=1, max_length=600)


class PlaygroundAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str = Field(min_length=1, max_length=4000)
    outcome: Literal["grounded", "fallback"]
    citations: list[PlaygroundCitation] = Field(max_length=5)


ERROR_STATUS = {
    "assistant_not_found": status.HTTP_404_NOT_FOUND,
    "knowledge_not_ready": status.HTTP_409_CONFLICT,
    "draft_changed": status.HTTP_409_CONFLICT,
    "rag_invalid_request": 422,
}
SAFE_SERVICE_ERRORS = {
    "rag_unavailable", "retrieval_unavailable", "retrieval_invalid_output",
    "embedding_unavailable", "embedding_space_mismatch", "embedding_invalid_output",
    "embedding_configuration", "embedding_input_limit", "embedding_auth",
    "embedding_quota_or_rate_limited", "embedding_model_unavailable", "embedding_timeout",
    "generation_configuration", "generation_input_limit", "generation_auth",
    "generation_rate_limited", "generation_model_unavailable", "generation_timeout",
    "generation_unavailable", "generation_invalid_output", "retrieval_configuration",
    "generation_output_invalid_json", "generation_output_invalid_envelope",
    "generation_output_invalid_usage", "generation_output_incomplete",
    "generation_output_refused", "generation_output_invalid_schema",
    "generation_output_invalid_citation", "generation_output_too_large",
}
ERROR_MESSAGE = {
    "assistant_not_found": "Assistant not found",
    "knowledge_not_ready": "Knowledge is not ready. Prepare or refresh the assistant knowledge, then retry.",
    "draft_changed": "Assistant or knowledge changed during this request. Please retry.",
    "rag_invalid_request": "Provide a non-empty message within the allowed length.",
}


def get_rag_orchestrator(request: Request) -> RagOrchestrator:
    orchestrator = getattr(request.app.state, "rag_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail={
            "code": "playground_unavailable", "message": "Playground is not configured."
        })
    return orchestrator


@router.post("/messages", response_model=PlaygroundAnswer)
async def send_message(assistant_id: UUID, payload: PlaygroundMessageRequest,
                       response: Response, owner: OwnerContext = CurrentOwner,
                       orchestrator: RagOrchestrator = Depends(get_rag_orchestrator)) -> PlaygroundAnswer:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        answer = await orchestrator.answer(owner.owner_id, assistant_id, payload.message)
        return PlaygroundAnswer(
            answer=answer.answer, outcome=answer.outcome,
            citations=[PlaygroundCitation(file_id=item.file_id, chunk_id=item.chunk_id,
                filename=item.filename, excerpt=item.excerpt) for item in answer.citations],
        )
    except RagFailure as exc:
        code = exc.code if exc.code in ERROR_STATUS or exc.code in SAFE_SERVICE_ERRORS else "playground_unavailable"
        body = {"detail": {
            "code": code,
            "message": ERROR_MESSAGE.get(code, "Playground could not complete this request. Please retry."),
        }}
        if exc.fallback_message is not None:
            body["fallback_message"] = exc.fallback_message
        return JSONResponse(status_code=ERROR_STATUS.get(code, status.HTTP_503_SERVICE_UNAVAILABLE),
                            content=body,
                            headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
