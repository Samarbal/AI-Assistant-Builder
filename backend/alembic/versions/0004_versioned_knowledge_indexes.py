"""Add immutable, owner-scoped semantic index versions and pgvector chunks.

Requires the pgvector extension preinstalled in the `public` schema. This
migration deliberately does not create extensions or modify Supabase resources.
"""
from alembic import op

revision = "0004_versioned_knowledge_indexes"
down_revision = "0003_knowledge_files"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
                     JOIN pg_type t ON t.typnamespace=n.oid AND t.typname='vector'
                     WHERE e.extname='vector' AND n.nspname='public') THEN
        RAISE EXCEPTION 'Prerequisite missing: pgvector type public.vector is required';
      END IF;
      IF NOT has_schema_privilege('assistant_runtime','public','USAGE') THEN
        RAISE EXCEPTION 'Prerequisite missing: assistant_runtime needs USAGE on schema public';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='assistant_runtime'
                     AND NOT rolsuper AND NOT rolbypassrls) THEN
        RAISE EXCEPTION 'Prerequisite missing: restricted assistant_runtime role';
      END IF;
      IF current_user='assistant_runtime' THEN
        RAISE EXCEPTION 'Run this migration with the separate migration role';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner
                     WHERE c.oid='public.assistants'::regclass AND c.relrowsecurity
                       AND c.relforcerowsecurity AND r.rolname <> 'assistant_runtime') THEN
        RAISE EXCEPTION 'Prerequisite mismatch: assistants must retain forced owner RLS';
      END IF;
      IF to_regclass('public.knowledge_indexes') IS NOT NULL
         OR to_regclass('public.knowledge_index_sources') IS NOT NULL
         OR to_regclass('public.knowledge_index_batches') IS NOT NULL
         OR to_regclass('public.knowledge_chunks') IS NOT NULL
         OR EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid='public.assistants'::regclass
                    AND attname='active_knowledge_index_id' AND NOT attisdropped) THEN
        RAISE EXCEPTION 'Unexpected indexing schema objects already exist; review before migration';
      END IF;
      IF EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename IN
                 ('knowledge_indexes','knowledge_index_sources','knowledge_index_batches','knowledge_chunks')) THEN
        RAISE EXCEPTION 'Review existing index policies before migration';
      END IF;
    END $$""")
    op.execute("""
CREATE TABLE public.knowledge_indexes (
 id UUID PRIMARY KEY, owner_id UUID NOT NULL, assistant_id UUID NOT NULL,
 version INTEGER NOT NULL, idempotency_key UUID NOT NULL, manifest_sha256 VARCHAR(64) NOT NULL,
 embedding_provider VARCHAR(32) NOT NULL, embedding_model VARCHAR(100) NOT NULL,
 vector_dimension INTEGER NOT NULL, tokenizer_version VARCHAR(128) NOT NULL,
 chunker_version VARCHAR(256) NOT NULL, state VARCHAR(16) NOT NULL DEFAULT 'building',
 operation_id UUID NOT NULL, lease_expires_at TIMESTAMPTZ NOT NULL,
 total_chunks INTEGER NOT NULL, completed_chunks INTEGER NOT NULL DEFAULT 0,
 reserved_cost_microusd BIGINT NOT NULL DEFAULT 0, error_code VARCHAR(64),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 ready_at TIMESTAMPTZ,
 CONSTRAINT fk_index_assistant_owner FOREIGN KEY (assistant_id, owner_id)
   REFERENCES public.assistants(id, owner_id),
 CONSTRAINT uq_index_identity UNIQUE(id, assistant_id, owner_id),
 CONSTRAINT uq_index_version UNIQUE(assistant_id, owner_id, version),
 CONSTRAINT uq_index_request UNIQUE(assistant_id, owner_id, idempotency_key),
 CONSTRAINT ck_index_version CHECK(version > 0),
 CONSTRAINT ck_index_state CHECK(state IN ('building','ready','failed','superseded')),
 CONSTRAINT ck_index_dimension CHECK(vector_dimension=768),
 CONSTRAINT ck_index_total_chunks CHECK(total_chunks BETWEEN 1 AND 200),
 CONSTRAINT ck_index_completed_chunks CHECK(completed_chunks BETWEEN 0 AND total_chunks),
 CONSTRAINT ck_index_ready_complete CHECK((state='ready' AND ready_at IS NOT NULL AND completed_chunks=total_chunks) OR (state<>'ready' AND ready_at IS NULL)),
 CONSTRAINT ck_index_manifest_hash CHECK(length(manifest_sha256)=64),
 CONSTRAINT ck_index_reserved_cost CHECK(reserved_cost_microusd BETWEEN 0 AND 100000)
)
""")
    op.execute("CREATE UNIQUE INDEX uq_index_one_building ON public.knowledge_indexes(assistant_id) WHERE state='building'")
    op.execute("CREATE INDEX ix_index_owner_assistant_state ON public.knowledge_indexes(owner_id,assistant_id,state)")
    op.execute("""
CREATE TABLE public.knowledge_index_sources (
 index_id UUID NOT NULL, file_id UUID NOT NULL, assistant_id UUID NOT NULL, owner_id UUID NOT NULL,
 extraction_version VARCHAR(64) NOT NULL, source_sha256 VARCHAR(64) NOT NULL,
 PRIMARY KEY(index_id,file_id),
 CONSTRAINT uq_index_source_identity UNIQUE(index_id,file_id,assistant_id,owner_id),
 CONSTRAINT fk_index_source_index FOREIGN KEY(index_id,assistant_id,owner_id)
   REFERENCES public.knowledge_indexes(id,assistant_id,owner_id),
 CONSTRAINT fk_index_source_file FOREIGN KEY(file_id,assistant_id,owner_id)
   REFERENCES public.knowledge_files(id,assistant_id,owner_id),
 CONSTRAINT ck_index_source_hash CHECK(length(source_sha256)=64)
)
""")
    op.execute("CREATE INDEX ix_index_source_owner_assistant ON public.knowledge_index_sources(owner_id,assistant_id,file_id)")
    op.execute("""
CREATE TABLE public.knowledge_index_batches (
 id UUID PRIMARY KEY, index_id UUID NOT NULL, assistant_id UUID NOT NULL, owner_id UUID NOT NULL,
 batch_number INTEGER NOT NULL, idempotency_key UUID NOT NULL, request_sha256 VARCHAR(64) NOT NULL,
 chunk_ids JSONB NOT NULL, reserved_tokens INTEGER NOT NULL, reserved_cost_microusd BIGINT NOT NULL,
 state VARCHAR(16) NOT NULL DEFAULT 'pending', operation_id UUID NOT NULL,
 lease_expires_at TIMESTAMPTZ NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 actual_tokens INTEGER, error_code VARCHAR(64), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT fk_index_batch_index FOREIGN KEY(index_id,assistant_id,owner_id)
   REFERENCES public.knowledge_indexes(id,assistant_id,owner_id),
 CONSTRAINT uq_index_batch_number UNIQUE(index_id,batch_number),
 CONSTRAINT uq_index_batch_idempotency UNIQUE(index_id,idempotency_key),
 CONSTRAINT ck_index_batch_number CHECK(batch_number >= 0),
 CONSTRAINT ck_index_batch_state CHECK(state IN ('pending','inflight','completed','uncertain','failed')),
 CONSTRAINT ck_index_batch_tokens CHECK(reserved_tokens BETWEEN 1 AND 4800),
 CONSTRAINT ck_index_batch_cost CHECK(reserved_cost_microusd >= 0),
 CONSTRAINT ck_index_batch_actual_tokens CHECK(actual_tokens IS NULL OR actual_tokens >= 0),
 CONSTRAINT ck_index_batch_attempts CHECK(attempts >= 0),
 CONSTRAINT ck_index_batch_hash CHECK(length(request_sha256)=64),
 CONSTRAINT ck_index_batch_chunk_ids CHECK(jsonb_typeof(chunk_ids)='array' AND jsonb_array_length(chunk_ids) BETWEEN 1 AND 8)
)
""")
    op.execute("CREATE INDEX ix_index_batch_recovery ON public.knowledge_index_batches(state,lease_expires_at)")
    op.execute("""
CREATE TABLE public.knowledge_chunks (
 id UUID PRIMARY KEY, index_id UUID NOT NULL, owner_id UUID NOT NULL, assistant_id UUID NOT NULL,
 file_id UUID NOT NULL, ordinal INTEGER NOT NULL, extraction_version VARCHAR(64) NOT NULL,
 chunker_version VARCHAR(256) NOT NULL, source_sha256 VARCHAR(64) NOT NULL,
 start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, token_count INTEGER NOT NULL,
 text_sha256 VARCHAR(64) NOT NULL, chunk_text TEXT NOT NULL,
 embedding public.vector(768) NOT NULL,
 CONSTRAINT fk_chunk_index FOREIGN KEY(index_id,assistant_id,owner_id)
   REFERENCES public.knowledge_indexes(id,assistant_id,owner_id),
 CONSTRAINT fk_chunk_source FOREIGN KEY(index_id,file_id,assistant_id,owner_id)
   REFERENCES public.knowledge_index_sources(index_id,file_id,assistant_id,owner_id),
 CONSTRAINT uq_chunk_source_ordinal UNIQUE(index_id,file_id,ordinal),
 CONSTRAINT ck_chunk_offsets CHECK(ordinal>=0 AND start_offset>=0 AND end_offset>start_offset),
 CONSTRAINT ck_chunk_tokens CHECK(token_count BETWEEN 1 AND 600),
 CONSTRAINT ck_chunk_hashes CHECK(length(source_sha256)=64 AND length(text_sha256)=64)
)
""")
    op.execute("CREATE INDEX ix_chunk_owner_assistant_index ON public.knowledge_chunks(owner_id,assistant_id,index_id)")
    op.execute("CREATE INDEX ix_chunk_file_order ON public.knowledge_chunks(index_id,file_id,ordinal)")
    op.execute("ALTER TABLE public.assistants ADD COLUMN active_knowledge_index_id UUID")
    op.execute("""ALTER TABLE public.assistants ADD CONSTRAINT fk_assistant_active_index
      FOREIGN KEY(active_knowledge_index_id,id,owner_id)
      REFERENCES public.knowledge_indexes(id,assistant_id,owner_id)""")
    for table in ("knowledge_indexes", "knowledge_index_sources", "knowledge_index_batches", "knowledge_chunks"):
        op.execute(f"""DO $$ DECLARE target text; col record; recipient text;
          BEGIN
            FOREACH target IN ARRAY ARRAY['PUBLIC','anon','authenticated','service_role','assistant_runtime'] LOOP
              IF target='PUBLIC' OR EXISTS (SELECT FROM pg_roles WHERE rolname=target) THEN
                recipient := CASE WHEN target='PUBLIC' THEN 'PUBLIC' ELSE quote_ident(target) END;
                EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE public.{table} FROM ' || recipient;
                FOR col IN SELECT attname FROM pg_attribute WHERE attrelid='public.{table}'::regclass
                  AND attnum>0 AND NOT attisdropped LOOP
                  EXECUTE format('REVOKE ALL PRIVILEGES (%I) ON TABLE public.{table} FROM %s',col.attname,recipient);
                END LOOP;
              END IF;
            END LOOP;
          END $$""")
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT ON public.{table} TO assistant_runtime")
        predicate = "owner_id = NULLIF(current_setting('app.owner_id', true), '')::uuid"
        op.execute(f"CREATE POLICY {table}_select ON public.{table} FOR SELECT TO assistant_runtime USING ({predicate})")
        insert_check = predicate
        if table == "knowledge_indexes":
            insert_check += " AND state='building' AND completed_chunks=0 AND ready_at IS NULL"
        elif table == "knowledge_index_batches":
            insert_check += " AND state='pending' AND attempts=0 AND actual_tokens IS NULL"
        op.execute(f"CREATE POLICY {table}_insert ON public.{table} FOR INSERT TO assistant_runtime WITH CHECK ({insert_check})")
    op.execute("""GRANT UPDATE(state,operation_id,lease_expires_at,completed_chunks,reserved_cost_microusd,
      error_code,updated_at,ready_at) ON public.knowledge_indexes TO assistant_runtime""")
    op.execute("""CREATE POLICY knowledge_indexes_update ON public.knowledge_indexes FOR UPDATE TO assistant_runtime
      USING (owner_id=NULLIF(current_setting('app.owner_id',true),'')::uuid)
      WITH CHECK (owner_id=NULLIF(current_setting('app.owner_id',true),'')::uuid)""")
    op.execute("""GRANT UPDATE(state,operation_id,lease_expires_at,attempts,actual_tokens,
      reserved_cost_microusd,error_code,updated_at) ON public.knowledge_index_batches TO assistant_runtime""")
    op.execute("""CREATE POLICY knowledge_index_batches_update ON public.knowledge_index_batches FOR UPDATE TO assistant_runtime
      USING (owner_id=NULLIF(current_setting('app.owner_id',true),'')::uuid)
      WITH CHECK (owner_id=NULLIF(current_setting('app.owner_id',true),'')::uuid)""")
    op.execute("GRANT UPDATE(active_knowledge_index_id,updated_at) ON public.assistants TO assistant_runtime")


def downgrade():
    raise RuntimeError("Indexed vectors and recovery state require a reviewed non-destructive rollback")
