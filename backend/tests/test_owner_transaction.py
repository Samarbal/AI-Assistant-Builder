from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from assistant_builder.auth import OwnerContext
from assistant_builder.db import get_db_session, set_owner_identity
from assistant_builder.main import create_app
from .test_phase1_contracts import OWNER_A


def test_identity_is_set_before_session_is_yielded():
    factory = MagicMock()
    session = factory.begin.return_value.__enter__.return_value
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_factory=factory)))
    dependency = get_db_session(request, OwnerContext(OWNER_A))
    assert next(dependency) is session
    statement, params = session.execute.call_args.args
    assert "set_config('app.owner_id', :owner_id, true)" in str(statement)
    assert params == {"owner_id": str(OWNER_A)}
    with pytest.raises(StopIteration):
        next(dependency)


def test_invalid_owner_never_executes_sql():
    session = MagicMock()
    with pytest.raises(ValueError):
        set_owner_identity(session, "client-chosen-value")
    session.execute.assert_not_called()


def test_missing_auth_never_opens_session():
    app = create_app()
    factory = MagicMock()
    app.state.session_factory = factory
    assert TestClient(app).get("/assistants").status_code == 401
    factory.begin.assert_not_called()
