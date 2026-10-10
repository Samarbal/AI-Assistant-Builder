from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from fastapi import Request, HTTPException

from .config import get_settings


def create_database_engine() -> Engine:
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for database-backed operations")
    return create_engine(database_url, pool_pre_ping=True)


def get_db_session(request: Request) -> Generator[Session, None, None]:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(503, "Database unavailable")
    # begin commits on success, rolls back on failure, and closes the session.
    # The caller must use function scope so commit precedes the HTTP response.
    with session_factory.begin() as session:
        yield session
