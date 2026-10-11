from collections.abc import Generator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session
from fastapi import Request, HTTPException, Depends
from uuid import UUID
from .auth import OwnerContext, get_current_owner

from .config import get_settings


def create_database_engine() -> Engine:
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for the restricted runtime connection")
    return create_engine(database_url, pool_pre_ping=True, hide_parameters=True)


def set_owner_identity(session: Session, owner_id: UUID) -> None:
    if not isinstance(owner_id, UUID):
        raise ValueError("Verified owner UUID required")
    session.execute(
        text("SELECT set_config('app.owner_id', :owner_id, true)"),
        {"owner_id": str(owner_id)},
    )


def validate_runtime_role(engine: Engine) -> None:
    """Reject privileged/misconfigured runtime connections before serving requests."""
    with engine.connect() as connection:
        safe = connection.scalar(text("""
            SELECT current_user = 'assistant_runtime'
              AND NOT r.rolsuper AND NOT r.rolbypassrls
              AND NOT r.rolcreaterole AND NOT r.rolcreatedb AND NOT r.rolreplication
              AND NOT EXISTS (
                  SELECT 1 FROM pg_roles other WHERE other.oid <> r.oid
                  AND pg_has_role(r.oid, other.oid, 'MEMBER'))
              AND c.relowner <> r.oid AND c.relrowsecurity AND c.relforcerowsecurity
              AND NOT has_schema_privilege(current_user, 'public', 'CREATE')
              AND NOT has_table_privilege(current_user, 'public.assistants', 'DELETE')
              AND NOT has_table_privilege(current_user, 'public.assistants', 'TRUNCATE')
              AND NOT has_column_privilege(current_user, 'public.assistants', 'owner_id', 'UPDATE')
            FROM pg_roles r JOIN pg_class c ON c.oid = to_regclass('public.assistants')
            WHERE r.rolname = current_user
        """))
        if safe is not True:
            raise RuntimeError("Runtime database role or assistant RLS configuration is unsafe")


def get_db_session(
    request: Request, owner: OwnerContext = Depends(get_current_owner)
) -> Generator[Session, None, None]:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(503, "Database unavailable")
    # begin commits on success, rolls back on failure, and closes the session.
    # The caller must use function scope so commit precedes the HTTP response.
    with session_factory.begin() as session:
        set_owner_identity(session, owner.owner_id)
        yield session
