"""Restrict assistants to the trusted FastAPI runtime boundary.

Revision ID: 0002_assistant_owner_rls
Revises: 0001_create_assistants
"""
from alembic import op

revision = "0002_assistant_owner_rls"
down_revision = "0001_create_assistants"
branch_labels = None
depends_on = None


def upgrade():
    # Alembic creates this table before revisions run. Secure it before the
    # shared migration transaction commits; never change project default ACLs.
    op.execute("""
        DO $$ DECLARE target text; col record; recipient text;
        BEGIN
          FOREACH target IN ARRAY ARRAY['PUBLIC','anon','authenticated','service_role','assistant_runtime'] LOOP
            IF target = 'PUBLIC' OR EXISTS (SELECT FROM pg_roles WHERE rolname=target) THEN
              recipient := CASE WHEN target='PUBLIC' THEN 'PUBLIC' ELSE quote_ident(target) END;
              EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE public.alembic_version FROM ' || recipient;
              FOR col IN SELECT attname FROM pg_attribute
                WHERE attrelid='public.alembic_version'::regclass AND attnum>0 AND NOT attisdropped LOOP
                EXECUTE format('REVOKE ALL PRIVILEGES (%I) ON TABLE public.alembic_version FROM %s', col.attname, recipient);
              END LOOP;
            END IF;
          END LOOP;
        END $$;
    """)
    # No API policies. Migration table owner retains access for Alembic updates.
    # REVOKE above is essential: RLS alone does not restrict TRUNCATE.
    op.execute("ALTER TABLE public.alembic_version ENABLE ROW LEVEL SECURITY")
    # Provision the login separately. Never put its password in a migration.
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'assistant_runtime') THEN
            RAISE EXCEPTION 'Provision assistant_runtime before this migration';
          END IF;
          IF EXISTS (SELECT FROM pg_policies WHERE schemaname='public' AND tablename='assistants') THEN
            RAISE EXCEPTION 'Review existing assistant policies before migration';
          END IF;
        END $$;
    """)
    # Revoke both table and column ACLs; table REVOKE alone leaves column grants.
    op.execute("""
        DO $$ DECLARE target text; col record; recipient text;
        BEGIN
          FOREACH target IN ARRAY ARRAY['PUBLIC','anon','authenticated','service_role','assistant_runtime'] LOOP
            IF target = 'PUBLIC' OR EXISTS (SELECT FROM pg_roles WHERE rolname=target) THEN
              recipient := CASE WHEN target='PUBLIC' THEN 'PUBLIC' ELSE quote_ident(target) END;
              EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE public.assistants FROM ' || recipient;
              FOR col IN SELECT attname FROM pg_attribute
                WHERE attrelid='public.assistants'::regclass AND attnum>0 AND NOT attisdropped LOOP
                EXECUTE format('REVOKE ALL PRIVILEGES (%I) ON TABLE public.assistants FROM %s', col.attname, recipient);
              END LOOP;
            END IF;
          END LOOP;
        END $$;
    """)
    op.execute("GRANT USAGE ON SCHEMA public TO assistant_runtime")
    op.execute("GRANT SELECT, INSERT ON public.assistants TO assistant_runtime")
    op.execute("""GRANT UPDATE
        (name, role, colors, response_style, tone, fallback_message, updated_at)
        ON public.assistants TO assistant_runtime""")
    op.execute("ALTER TABLE public.assistants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.assistants FORCE ROW LEVEL SECURITY")
    predicate = "owner_id = NULLIF(current_setting('app.owner_id', true), '')::uuid"
    op.execute(f"CREATE POLICY assistant_select ON public.assistants FOR SELECT TO assistant_runtime USING ({predicate})")
    op.execute(f"CREATE POLICY assistant_insert ON public.assistants FOR INSERT TO assistant_runtime WITH CHECK ({predicate})")
    op.execute(f"CREATE POLICY assistant_update ON public.assistants FOR UPDATE TO assistant_runtime USING ({predicate}) WITH CHECK ({predicate})")


def downgrade():
    # Reverting to unrestricted data access is not a safe automatic rollback.
    raise RuntimeError("Security migration downgrade requires an explicit reviewed recovery procedure")
