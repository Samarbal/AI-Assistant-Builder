"""Authenticated owner APIs for visitor conversation history."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import CurrentOwner, OwnerContext
from .conversation_history import (ConversationHistoryNotFound, ConversationHistoryService,
                                  ConversationHistoryUnavailable, InvalidHistoryCursor)
from .db import get_db_session

router = APIRouter(prefix="/assistants/{assistant_id}/conversations", tags=["conversation-history"])


class ConversationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID
    created_at: datetime
    last_activity_at: datetime | None
    latest_status: Literal["idle", "pending", "completed", "fallback", "failed", "uncertain", "version_changed"]
    latest_outcome: Literal["grounded", "fallback"] | None
    latest_published_version: int | None = Field(default=None, ge=1)


class ConversationListRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ConversationSummary]
    next_cursor: str | None
    limit: int = Field(ge=1, le=100)


class ConversationTurnRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_message: str
    user_created_at: datetime
    assistant_message: str | None
    assistant_created_at: datetime | None
    status: Literal["pending", "completed", "fallback", "failed", "uncertain", "version_changed"]
    outcome: Literal["grounded", "fallback"] | None
    published_version: int = Field(ge=1)


class ConversationDetailRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID
    created_at: datetime
    turns: list[ConversationTurnRead]
    next_cursor: str | None
    limit: int = Field(ge=1, le=100)


def get_history_service(session: Session = Depends(get_db_session, scope="function")) -> ConversationHistoryService:
    return ConversationHistoryService(session)


def _run(call):
    try:
        return call()
    except ConversationHistoryNotFound:
        raise HTTPException(404, "Assistant or conversation not found") from None
    except InvalidHistoryCursor:
        raise HTTPException(422, "Invalid history cursor") from None
    except (ConversationHistoryUnavailable, SQLAlchemyError):
        raise HTTPException(503, "Conversation history unavailable") from None


@router.get("", response_model=ConversationListRead)
def list_conversations(assistant_id: UUID, owner: OwnerContext = CurrentOwner,
                       limit: int = Query(default=20, ge=1, le=100),
                       cursor: str | None = Query(default=None, max_length=256),
                       service: ConversationHistoryService = Depends(get_history_service)):
    return _run(lambda: service.list_conversations(owner.owner_id, assistant_id,
                                                   limit=limit, cursor=cursor))


@router.get("/{conversation_id}", response_model=ConversationDetailRead)
def get_conversation(assistant_id: UUID, conversation_id: UUID, owner: OwnerContext = CurrentOwner,
                     limit: int = Query(default=20, ge=1, le=100),
                     cursor: str | None = Query(default=None, max_length=256),
                     service: ConversationHistoryService = Depends(get_history_service)):
    return _run(lambda: service.get_conversation(owner.owner_id, assistant_id, conversation_id,
                                                 limit=limit, cursor=cursor))
