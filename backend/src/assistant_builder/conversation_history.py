"""Owner-scoped read model for persisted public visitor conversations."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


class ConversationHistoryNotFound(Exception):
    pass


class InvalidHistoryCursor(Exception):
    pass


class ConversationHistoryUnavailable(Exception):
    pass


@dataclass(frozen=True)
class HistoryCursor:
    created_at: datetime
    row_id: UUID


def encode_cursor(created_at: datetime, row_id: UUID) -> str:
    if created_at.tzinfo is None:
        raise ValueError("Cursor timestamp must include a timezone")
    raw = f"{created_at.isoformat()}|{row_id}".encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str | None) -> HistoryCursor | None:
    if value is None:
        return None
    if not value or len(value) > 256:
        raise InvalidHistoryCursor
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != value:
            raise ValueError
        timestamp, identifier = raw.decode("ascii").split("|", 1)
        created_at = datetime.fromisoformat(timestamp)
        row_id = UUID(identifier)
        if created_at.tzinfo is None:
            raise ValueError
        return HistoryCursor(created_at, row_id)
    except (ValueError, UnicodeError, TypeError):
        raise InvalidHistoryCursor from None


_SAFE_STATES = {"pending", "completed", "fallback", "failed", "uncertain", "version_rejected"}


def _safe_turn(row) -> dict:
    state = row["state"]
    if state not in _SAFE_STATES:
        state = "failed"
    status = "version_changed" if state == "version_rejected" else state
    answer = row["answer_text"] if state in {"completed", "fallback"} else None
    outcome = row["outcome"] if state in {"completed", "fallback"} else None
    if answer is None or outcome not in {"grounded", "fallback"}:
        if state in {"completed", "fallback"}:
            status, answer, outcome = "failed", None, None
    if (state == "completed" and outcome != "grounded") or (state == "fallback" and outcome != "fallback"):
        status, answer, outcome = "failed", None, None
    return {
        "user_message": row["user_text"],
        "user_created_at": row["created_at"],
        "assistant_message": answer,
        "assistant_created_at": row["completed_at"] if answer is not None else None,
        "status": status,
        "outcome": outcome,
        "published_version": row["version"],
    }


class ConversationHistoryService:
    """Read-only history use cases. RLS and explicit owner predicates both apply."""

    def __init__(self, session: Session):
        self.session = session

    def _require_assistant(self, owner_id: UUID, assistant_id: UUID) -> None:
        row = self.session.execute(text("""
            SELECT id FROM public.assistants
             WHERE id=:assistant_id AND owner_id=:owner_id
        """), {"assistant_id": assistant_id, "owner_id": owner_id}).scalar_one_or_none()
        if row is None:
            raise ConversationHistoryNotFound

    def list_conversations(self, owner_id: UUID, assistant_id: UUID, *, limit: int,
                           cursor: str | None = None) -> dict:
        position = decode_cursor(cursor)
        try:
            self._require_assistant(owner_id, assistant_id)
            cursor_filter = ""
            params = {"assistant_id": assistant_id, "owner_id": owner_id, "limit": limit + 1}
            if position is not None:
                cursor_filter = "AND (c.created_at,c.id)<(:cursor_at,:cursor_id)"
                params.update(cursor_at=position.created_at, cursor_id=position.row_id)
            rows = self.session.execute(text(f"""
                SELECT c.id,c.created_at,latest.created_at AS last_activity_at,
                       latest.state AS latest_state,latest.outcome AS latest_outcome,
                       latest.version AS latest_version
                  FROM public.visitor_conversations c
                  LEFT JOIN LATERAL (
                    SELECT t.created_at,t.state,t.outcome,s.version
                      FROM public.visitor_turns t
                      LEFT JOIN public.published_snapshots s
                        ON s.id=t.snapshot_id AND s.owner_id=t.owner_id AND s.assistant_id=t.assistant_id
                     WHERE t.conversation_id=c.id AND t.owner_id=c.owner_id AND t.assistant_id=c.assistant_id
                     ORDER BY t.created_at DESC,t.id DESC LIMIT 1
                  ) latest ON TRUE
                 WHERE c.assistant_id=:assistant_id AND c.owner_id=:owner_id {cursor_filter}
                 ORDER BY c.created_at DESC,c.id DESC LIMIT :limit
            """), params).mappings().all()
        except ConversationHistoryNotFound:
            raise
        except SQLAlchemyError:
            raise ConversationHistoryUnavailable from None

        has_more = len(rows) > limit
        page = rows[:limit]
        items = []
        for row in page:
            state = row["latest_state"]
            if state not in _SAFE_STATES:
                state = "failed" if state is not None else "idle"
            items.append({
                "conversation_id": row["id"],
                "created_at": row["created_at"],
                "last_activity_at": row["last_activity_at"],
                "latest_status": "version_changed" if state == "version_rejected" else state,
                "latest_outcome": row["latest_outcome"] if state in {"completed", "fallback"} else None,
                "latest_published_version": row["latest_version"],
            })
        next_cursor = encode_cursor(page[-1]["created_at"], page[-1]["id"]) if has_more and page else None
        return {"items": items, "next_cursor": next_cursor, "limit": limit}

    def get_conversation(self, owner_id: UUID, assistant_id: UUID, conversation_id: UUID, *,
                         limit: int, cursor: str | None = None) -> dict:
        position = decode_cursor(cursor)
        try:
            self._require_assistant(owner_id, assistant_id)
            conversation = self.session.execute(text("""
                SELECT id,created_at FROM public.visitor_conversations
                 WHERE id=:conversation_id AND assistant_id=:assistant_id AND owner_id=:owner_id
            """), {"conversation_id": conversation_id, "assistant_id": assistant_id,
                   "owner_id": owner_id}).mappings().one_or_none()
            if conversation is None:
                raise ConversationHistoryNotFound
            cursor_filter = ""
            params = {"conversation_id": conversation_id, "assistant_id": assistant_id,
                      "owner_id": owner_id, "limit": limit + 1}
            if position is not None:
                cursor_filter = "AND (t.created_at,t.id)>(:cursor_at,:cursor_id)"
                params.update(cursor_at=position.created_at, cursor_id=position.row_id)
            rows = self.session.execute(text(f"""
                SELECT t.id,t.user_text,t.state,t.answer_text,t.outcome,t.created_at,t.completed_at,s.version
                  FROM public.visitor_turns t
                  JOIN public.published_snapshots s
                    ON s.id=t.snapshot_id AND s.owner_id=t.owner_id AND s.assistant_id=t.assistant_id
                 WHERE t.conversation_id=:conversation_id AND t.assistant_id=:assistant_id
                   AND t.owner_id=:owner_id {cursor_filter}
                 ORDER BY t.created_at,t.id LIMIT :limit
            """), params).mappings().all()
        except ConversationHistoryNotFound:
            raise
        except SQLAlchemyError:
            raise ConversationHistoryUnavailable from None

        has_more = len(rows) > limit
        page = rows[:limit]
        turns = [_safe_turn(row) for row in page]
        next_cursor = encode_cursor(page[-1]["created_at"], page[-1]["id"]) if has_more and page else None
        return {"conversation_id": conversation["id"], "created_at": conversation["created_at"],
                "turns": turns, "next_cursor": next_cursor, "limit": limit}
