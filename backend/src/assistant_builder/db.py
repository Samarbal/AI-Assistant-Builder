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


def create_public_database_engine() -> Engine:
    """Build only the dedicated public runtime connection; never fall back."""
    database_url = get_settings().public_database_url
    if not database_url:
        raise RuntimeError("PUBLIC_DATABASE_URL is required when public chat is enabled")
    return create_engine(database_url, pool_pre_ping=True, hide_parameters=True)


def validate_public_runtime_role(engine: Engine) -> None:
    """Fail closed unless the connection is the isolated, restricted public role."""
    with engine.connect() as connection:
        safe = connection.scalar(text("""
            SELECT current_user = 'assistant_public_runtime'
              AND NOT r.rolsuper AND NOT r.rolbypassrls
              AND NOT r.rolcreaterole AND NOT r.rolcreatedb AND NOT r.rolreplication
              AND NOT EXISTS (SELECT 1 FROM pg_roles other WHERE other.oid <> r.oid
                    AND pg_has_role(r.oid, other.oid, 'MEMBER'))
              AND NOT has_schema_privilege(current_user, 'public', 'CREATE')
              AND NOT has_any_column_privilege(current_user, 'public.assistants', 'SELECT')
              AND NOT has_any_column_privilege(current_user, 'public.assistants', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'public.assistants', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'public.assistants', 'DELETE')
              AND NOT has_table_privilege(current_user, 'public.assistants', 'TRUNCATE')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_files', 'SELECT')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_files', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_files', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'public.knowledge_files', 'DELETE')
              AND NOT has_table_privilege(current_user, 'public.knowledge_files', 'TRUNCATE')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_file_text', 'SELECT')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_file_text', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_file_text', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'public.knowledge_file_text', 'DELETE')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_indexes', 'SELECT')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_indexes', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_indexes', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'public.knowledge_indexes', 'DELETE')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_index_sources', 'SELECT')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_index_sources', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_index_sources', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'public.knowledge_index_sources', 'DELETE')
              AND has_any_column_privilege(current_user, 'public.assistant_publications', 'SELECT')
              AND has_any_column_privilege(current_user, 'public.published_snapshots', 'SELECT')
              AND has_any_column_privilege(current_user, 'public.published_sources', 'SELECT')
              AND has_any_column_privilege(current_user, 'public.knowledge_chunks', 'SELECT')
              AND NOT has_any_column_privilege(current_user, 'public.assistant_publications', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'public.assistant_publications', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'public.assistant_publications', 'DELETE')
              AND NOT has_any_column_privilege(current_user, 'public.published_snapshots', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'public.published_snapshots', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'public.published_snapshots', 'DELETE')
              AND NOT has_any_column_privilege(current_user, 'public.published_sources', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'public.published_sources', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'public.published_sources', 'DELETE')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_chunks', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'public.knowledge_chunks', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'public.knowledge_chunks', 'DELETE')
              AND NOT has_table_privilege(current_user, 'public.knowledge_chunks', 'TRUNCATE')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.budget_attempts', 'SELECT')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.budget_attempts', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.budget_attempts', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'ai_accounting.budget_attempts', 'DELETE')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.budget_day_holds', 'SELECT')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.budget_day_holds', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.budget_day_holds', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'ai_accounting.budget_day_holds', 'DELETE')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.budget_days', 'SELECT')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.budget_days', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.budget_days', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'ai_accounting.budget_days', 'DELETE')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.budget_operations', 'SELECT')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.budget_operations', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.budget_operations', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'ai_accounting.budget_operations', 'DELETE')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.price_versions', 'SELECT')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.price_versions', 'INSERT')
              AND NOT has_any_column_privilege(current_user, 'ai_accounting.price_versions', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'ai_accounting.price_versions', 'DELETE')
              AND has_any_column_privilege(current_user, 'public.visitor_conversations', 'INSERT')
              AND has_any_column_privilege(current_user, 'public.visitor_turns', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'public.visitor_conversations', 'UPDATE')
              AND NOT has_table_privilege(current_user, 'public.visitor_conversations', 'DELETE')
              AND NOT has_table_privilege(current_user, 'public.visitor_turns', 'DELETE')
              AND NOT has_table_privilege(current_user, 'public.visitor_conversations', 'TRUNCATE')
              AND NOT has_table_privilege(current_user, 'public.visitor_turns', 'TRUNCATE')
            FROM pg_roles r WHERE r.rolname=current_user
        """))
        if safe is not True:
            raise RuntimeError("Public runtime role or grants are unsafe")


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
