"""Phase 2 knowledge metadata, extraction storage and owner RLS (no Storage API)."""
from alembic import op

revision = "0003_knowledge_files"
down_revision = "0002_assistant_owner_rls"
branch_labels = None
depends_on = None

def upgrade():
    op.create_unique_constraint("uq_assistants_id_owner", "assistants", ["id", "owner_id"], schema="public")
    op.execute("""
CREATE TABLE public.knowledge_files (
	id UUID NOT NULL,
	owner_id UUID NOT NULL,
	assistant_id UUID NOT NULL,
	slot_number INTEGER,
	original_filename VARCHAR(255) NOT NULL,
	file_format VARCHAR(4) NOT NULL,
	size_bytes BIGINT NOT NULL,
	content_sha256 VARCHAR(64) NOT NULL,
	object_key VARCHAR(512) NOT NULL,
	processing_state VARCHAR(16) DEFAULT 'accepted' NOT NULL,
	error_code VARCHAR(64),
	operation_id UUID NOT NULL,
	lease_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	removed_at TIMESTAMP WITH TIME ZONE,
	cleanup_state VARCHAR(16) DEFAULT 'not_needed' NOT NULL,
	cleanup_attempts INTEGER DEFAULT '0' NOT NULL,
	cleanup_error_code VARCHAR(64),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT fk_knowledge_assistant_owner FOREIGN KEY(assistant_id, owner_id) REFERENCES public.assistants (id, owner_id),
	CONSTRAINT uq_knowledge_identity UNIQUE (id, assistant_id, owner_id),
	CONSTRAINT uq_knowledge_slot UNIQUE (assistant_id, slot_number),
	CONSTRAINT uq_knowledge_object_key UNIQUE (object_key),
	CONSTRAINT ck_knowledge_slot CHECK (slot_number IS NULL OR slot_number BETWEEN 1 AND 5),
	CONSTRAINT ck_knowledge_attachment CHECK ((removed_at IS NULL AND slot_number IS NOT NULL) OR (removed_at IS NOT NULL AND slot_number IS NULL)),
	CONSTRAINT ck_knowledge_size CHECK (size_bytes > 0 AND size_bytes <= 10000000),
	CONSTRAINT ck_knowledge_format CHECK (file_format IN ('pdf', 'docx')),
	CONSTRAINT ck_knowledge_state CHECK (processing_state IN ('accepted', 'processing', 'extracted', 'failed')),
	CONSTRAINT ck_knowledge_cleanup CHECK (cleanup_state IN ('not_needed', 'pending', 'complete')),
	CONSTRAINT ck_knowledge_cleanup_attempts CHECK (cleanup_attempts >= 0),
	CONSTRAINT ck_knowledge_hash CHECK (length(content_sha256) = 64)
)

""")
    op.execute('CREATE INDEX ix_knowledge_cleanup ON public.knowledge_files (cleanup_state, updated_at)')
    op.execute('CREATE INDEX ix_knowledge_owner_assistant ON public.knowledge_files (owner_id, assistant_id)')
    op.execute('CREATE INDEX ix_knowledge_recovery ON public.knowledge_files (processing_state, lease_expires_at)')
    op.execute("""
CREATE TABLE public.knowledge_file_text (
	file_id UUID NOT NULL,
	assistant_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	extracted_text TEXT NOT NULL,
	extraction_version VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (file_id),
	CONSTRAINT fk_knowledge_text_owner FOREIGN KEY(file_id, assistant_id, owner_id) REFERENCES public.knowledge_files (id, assistant_id, owner_id),
	CONSTRAINT ck_knowledge_text_nonempty CHECK (length(extracted_text) > 0)
)

""")
    op.execute('CREATE INDEX ix_knowledge_text_owner_assistant ON public.knowledge_file_text (owner_id, assistant_id)')
    for table in ("knowledge_files", "knowledge_file_text"):
        # Revoke both table and inherited default column grants before commit.
        op.execute(f"""
            DO $$ DECLARE target text; col record; recipient text;
            BEGIN
              FOREACH target IN ARRAY ARRAY['PUBLIC','anon','authenticated','service_role','assistant_runtime'] LOOP
                IF target='PUBLIC' OR EXISTS (SELECT FROM pg_roles WHERE rolname=target) THEN
                  recipient := CASE WHEN target='PUBLIC' THEN 'PUBLIC' ELSE quote_ident(target) END;
                  EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE public.{table} FROM ' || recipient;
                  FOR col IN SELECT attname FROM pg_attribute
                    WHERE attrelid='public.{table}'::regclass AND attnum>0 AND NOT attisdropped LOOP
                    EXECUTE format('REVOKE ALL PRIVILEGES (%I) ON TABLE public.{table} FROM %s', col.attname, recipient);
                  END LOOP;
                END IF;
              END LOOP;
            END $$;
        """)
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        predicate = "owner_id = NULLIF(current_setting('app.owner_id', true), '')::uuid"
        op.execute(f"GRANT SELECT, INSERT ON public.{table} TO assistant_runtime")
        op.execute(f"CREATE POLICY {table}_select ON public.{table} FOR SELECT TO assistant_runtime USING ({predicate})")
        op.execute(f"CREATE POLICY {table}_insert ON public.{table} FOR INSERT TO assistant_runtime WITH CHECK ({predicate})")
    predicate = "owner_id = NULLIF(current_setting('app.owner_id', true), '')::uuid"
    op.execute("""GRANT UPDATE (slot_number, processing_state, error_code, operation_id,
        lease_expires_at, removed_at, cleanup_state, cleanup_attempts, cleanup_error_code, updated_at)
        ON public.knowledge_files TO assistant_runtime""")
    op.execute(f"CREATE POLICY knowledge_files_update ON public.knowledge_files FOR UPDATE TO assistant_runtime USING ({predicate}) WITH CHECK ({predicate})")
    # Text and storage identity are immutable; no UPDATE or DELETE grants.


def downgrade():
    raise RuntimeError("Knowledge data rollback requires a reviewed recovery procedure; no automatic destructive downgrade")
