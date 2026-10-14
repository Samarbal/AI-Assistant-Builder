"""Explicitly authorized first deployment only. No existing objects are modified.

Run from backend. Reads local migration credentials; never prints exceptions/URLs.
Role and migrations share one transaction. Password is generated locally and only
its SCRAM verifier is sent as SQL. Runtime URL is saved in ignored .env after commit.
"""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import secrets

from alembic import command
from alembic.config import Config
from dotenv import dotenv_values, set_key
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from psycopg import sql

from assistant_builder.config import MigrationSettings
from phase1_baseline import verify_baseline


def scram_verifier(password):
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 4096)
    client = hmac.digest(salted, b"Client Key", "sha256")
    stored = hashlib.sha256(client).digest()
    server = hmac.digest(salted, b"Server Key", "sha256")
    b64 = lambda value: base64.b64encode(value).decode("ascii")
    return f"SCRAM-SHA-256$4096:{b64(salt)}${b64(stored)}:{b64(server)}"


def main():
    root = Path(__file__).resolve().parents[1]
    env = root / ".env"
    if dotenv_values(env).get("DATABASE_URL"):
        raise RuntimeError("Runtime URL already exists; review rather than overwrite")
    admin_url = make_url(MigrationSettings().migration_database_url)
    if admin_url.drivername != "postgresql+psycopg":
        raise RuntimeError("Explicit psycopg driver required")
    engine = create_engine(admin_url, hide_parameters=True, connect_args={"connect_timeout": 8})
    password = secrets.token_urlsafe(32)
    # Preserve the project suffix on a Supabase shared pooler login.
    suffix = admin_url.username.partition(".")[2]
    runtime_user = "assistant_runtime" + ("." + suffix if suffix else "")
    runtime_url = admin_url.set(username=runtime_user, password=password)
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                target = connection.execute(text("SELECT current_database(), current_user")).one()
                if tuple(target) != ("postgres", "postgres"):
                    raise RuntimeError("Unexpected target database or administrator")
                objects = connection.scalar(text("""SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f','S')"""))
                if objects:
                    raise RuntimeError("Unexpected public objects: stop before changes")
                if connection.scalar(text("SELECT EXISTS(SELECT FROM pg_roles WHERE rolname='assistant_runtime')")):
                    raise RuntimeError("Runtime role already exists")
                if connection.scalar(text("""SELECT EXISTS(SELECT FROM pg_namespace n,
                    LATERAL aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) a
                    WHERE n.nspname='public' AND a.grantee=0 AND a.privilege_type='CREATE')""")):
                    raise RuntimeError("PUBLIC schema CREATE requires separate review")
                verify_baseline(connection)
                print("Exact approved function and trigger baseline verified")
                print("Preflight passed: target confirmed; no public application objects or runtime role")
            with connection.begin():
                # Transactional DDL: a migration error also rolls back the role.
                raw = connection.connection.driver_connection
                raw.execute((root / "scripts/provision_runtime_role.sql").read_text())
                raw.execute(sql.SQL("ALTER ROLE assistant_runtime PASSWORD {}").format(sql.Literal(scram_verifier(password))))
                config = Config(str(root / "alembic.ini"))
                config.set_main_option("script_location", str(root / "alembic"))
                config.attributes["connection"] = connection
                # This reviewed deployment tool is Phase 1 only, even after new revisions exist.
                command.upgrade(config, "0002_assistant_owner_rls")
                for table in ("assistants", "alembic_version"):
                    for role in ("anon", "authenticated", "service_role", "assistant_runtime"):
                        for privilege in ("DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                            if connection.scalar(text("SELECT has_table_privilege(:r,:t,:p)"), {"r":role,"t":"public."+table,"p":privilege}):
                                raise RuntimeError("Unexpected effective table grants")
                print("Role and revisions prepared in one transaction; grants checked")
        set_key(str(env), "DATABASE_URL", runtime_url.render_as_string(hide_password=False))
        print(json.dumps({"deployed_revision":"0002_assistant_owner_rls", "runtime_role":"assistant_runtime", "runtime_url_saved":True}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # No traceback: SQL/provider exceptions can contain credential material.
        print("STOP: deployment/preflight failed:", type(exc).__name__, "; details suppressed; do not retry automatically")
        raise SystemExit(1)
