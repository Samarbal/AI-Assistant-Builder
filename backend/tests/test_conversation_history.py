from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from assistant_builder.conversation_history import (
    ConversationHistoryService, ConversationHistoryUnavailable, InvalidHistoryCursor,
    _safe_turn, decode_cursor, encode_cursor,
)


def test_cursor_round_trip_requires_timezone_and_rejects_noncanonical_input():
    created_at, identifier = datetime.now(timezone.utc), uuid4()
    encoded = encode_cursor(created_at, identifier)
    decoded = decode_cursor(encoded)
    assert decoded.row_id == identifier
    assert decoded.created_at == created_at
    for invalid in ("", "!", "e30", encoded + "="):
        with pytest.raises(InvalidHistoryCursor):
            decode_cursor(invalid)
    with pytest.raises(ValueError):
        encode_cursor(datetime.now(), identifier)


def test_history_database_failure_is_redacted():
    class BrokenSession:
        def execute(self, *_args, **_kwargs):
            raise SQLAlchemyError("private database detail")

    with pytest.raises(ConversationHistoryUnavailable) as caught:
        ConversationHistoryService(BrokenSession()).list_conversations(uuid4(), uuid4(), limit=20)
    assert "private database detail" not in str(caught.value)


@pytest.mark.parametrize("state", ["pending", "failed", "uncertain", "version_rejected"])
def test_unsuccessful_turn_never_projects_an_assistant_answer_or_internal_error(state):
    row = {
        "id": uuid4(), "user_text": "synthetic question", "state": state,
        "answer_text": "must not leak", "outcome": "grounded", "created_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc), "version": 2, "error_code": "provider_secret_detail",
    }
    result = _safe_turn(row)
    assert result["assistant_message"] is None
    assert result["assistant_created_at"] is None
    assert result["outcome"] is None
    assert "error_code" not in result and "snapshot_id" not in result
    if state == "version_rejected":
        assert result["status"] == "version_changed"
    else:
        assert result["status"] == state


def test_inconsistent_success_state_fails_closed():
    row = {"id": uuid4(), "user_text": "q", "state": "completed", "answer_text": None,
           "outcome": "grounded", "created_at": datetime.now(timezone.utc), "completed_at": None, "version": 1}
    assert _safe_turn(row)["status"] == "failed"
