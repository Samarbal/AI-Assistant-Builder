"""Allow the runtime to bind a prepare request key to its claimed batch.

Revision ID: 0005_batch_idem_grant
Revises: 0004_versioned_knowledge_indexes
"""
from alembic import op

revision = "0005_batch_idem_grant"
down_revision = "0004_versioned_knowledge_indexes"
branch_labels = None
depends_on = None


def upgrade():
    # Preserve the applied 0004 revision. Add only the missing column-level
    # permission; the existing forced-RLS UPDATE policy continues to scope rows.
    op.execute("""DO $$ BEGIN
      IF to_regclass('public.knowledge_index_batches') IS NULL THEN
        RAISE EXCEPTION 'Prerequisite missing: public.knowledge_index_batches';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='assistant_runtime'
                     AND NOT rolsuper AND NOT rolbypassrls) THEN
        RAISE EXCEPTION 'Prerequisite missing: restricted assistant_runtime role';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_class
                     WHERE oid='public.knowledge_index_batches'::regclass
                       AND relrowsecurity AND relforcerowsecurity) THEN
        RAISE EXCEPTION 'Prerequisite mismatch: knowledge_index_batches must retain forced RLS';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_policies
                     WHERE schemaname='public'
                       AND tablename='knowledge_index_batches'
                       AND policyname='knowledge_index_batches_update'
                       AND cmd='UPDATE'
                       AND 'assistant_runtime'::name = ANY(roles)
                       AND qual LIKE '%app.owner_id%'
                       AND with_check LIKE '%app.owner_id%') THEN
        RAISE EXCEPTION 'Prerequisite missing: owner-scoped batch UPDATE policy';
      END IF;
      IF current_user='assistant_runtime' THEN
        RAISE EXCEPTION 'Run this migration with the separate migration role';
      END IF;
    END $$""")
    op.execute("GRANT UPDATE (idempotency_key) ON public.knowledge_index_batches TO assistant_runtime")


def downgrade():
    raise RuntimeError("Security grant downgrade requires an explicit reviewed recovery procedure")
