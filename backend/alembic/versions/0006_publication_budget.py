"""Immutable publication records, restricted public runtime and shared AI budget.

Revision ID: 0006_publication_budget
Revises: 0005_batch_idem_grant
"""
from alembic import op

revision = "0006_publication_budget"
down_revision = "0005_batch_idem_grant"
branch_labels = None
depends_on = None


def upgrade():
    # Fail before creating anything when the applied Phase 1-3 baseline differs.
    op.execute("""
DO $$ BEGIN
  IF current_user IN ('assistant_runtime','assistant_public_runtime') THEN
    RAISE EXCEPTION 'P4 migration requires the separate migration connection';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='assistant_runtime' AND rolcanlogin
      AND NOT rolsuper AND NOT rolbypassrls AND NOT rolinherit AND NOT rolcreatedb
      AND NOT rolcreaterole AND NOT rolreplication) THEN
    RAISE EXCEPTION 'assistant_runtime role attributes differ from approved baseline';
  END IF;
  IF current_user IN ('assistant_public_runtime','assistant_budget_executor') THEN
    RAISE EXCEPTION 'Unexpected existing P4 role; inspect before migration';
  END IF;
  IF to_regclass('public.knowledge_files') IS NULL OR to_regclass('public.knowledge_file_text') IS NULL
     OR to_regclass('public.knowledge_indexes') IS NULL OR to_regclass('public.knowledge_index_sources') IS NULL
     OR to_regclass('public.knowledge_chunks') IS NULL
     OR NOT EXISTS (SELECT FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
                    WHERE e.extname='vector' AND n.nspname='public') THEN
    RAISE EXCEPTION 'Phase 2/3 and public.vector prerequisites are required';
  END IF;
  IF EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='public' AND c.relname IN
      ('assistant_publications','published_snapshots','published_sources','publication_requests',
       'visitor_conversations','visitor_turns')) OR to_regnamespace('ai_accounting') IS NOT NULL THEN
    RAISE EXCEPTION 'Unexpected P4 object already exists';
  END IF;
  IF EXISTS (SELECT FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid
      JOIN pg_roles u ON u.oid=m.member WHERE u.rolname='assistant_runtime') THEN
    RAISE EXCEPTION 'assistant_runtime has role membership; refusing privilege expansion';
  END IF;
  IF EXISTS (SELECT FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN
      ('assistant_publications','published_snapshots','published_sources','publication_requests',
       'visitor_conversations','visitor_turns')) THEN
    RAISE EXCEPTION 'Conflicting P4 table exists; inspect before migration';
  END IF;
END $$
""")
    op.execute("""
DO $$ BEGIN
  CREATE ROLE assistant_public_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
  CREATE ROLE assistant_budget_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
END $$
""")
    op.execute("""
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid
      JOIN pg_roles u ON u.oid=m.member WHERE u.rolname IN ('assistant_public_runtime','assistant_budget_executor')) THEN
    RAISE EXCEPTION 'P4 roles must not have memberships';
  END IF;
END $$
""")
    op.execute("DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO assistant_public_runtime',current_database()); END $$")
    op.execute("GRANT USAGE ON SCHEMA public TO assistant_public_runtime")
    op.execute("""
DO $$ BEGIN
  IF has_schema_privilege('assistant_public_runtime','public','CREATE') THEN
    RAISE EXCEPTION 'assistant_public_runtime inherits CREATE on public; review schema ACL before migration';
  END IF;
END $$
""")

    op.execute("""
CREATE TABLE public.assistant_publications (
  id uuid PRIMARY KEY, public_id uuid NOT NULL UNIQUE, assistant_id uuid NOT NULL, owner_id uuid NOT NULL,
  active_snapshot_id uuid, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(assistant_id,owner_id),
  UNIQUE(id,assistant_id,owner_id),
  FOREIGN KEY(assistant_id,owner_id) REFERENCES public.assistants(id,owner_id) ON DELETE RESTRICT
);
CREATE INDEX ix_publication_owner_assistant ON public.assistant_publications(owner_id,assistant_id);

CREATE TABLE public.published_snapshots (
  id uuid PRIMARY KEY, assistant_id uuid NOT NULL, owner_id uuid NOT NULL, version integer NOT NULL,
  state varchar(12) NOT NULL DEFAULT 'building', config jsonb NOT NULL, draft_fingerprint varchar(64) NOT NULL, knowledge_index_id uuid,
  embedding_provider varchar(32), embedding_model varchar(100), vector_dimension integer,
  retrieval_min_similarity double precision, manifest_sha256 varchar(64) NOT NULL,
  source_count integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), activated_at timestamptz NOT NULL,
  build_xid bigint NOT NULL DEFAULT txid_current(),
  UNIQUE(id,assistant_id,owner_id), UNIQUE(assistant_id,owner_id,version),
  FOREIGN KEY(assistant_id,owner_id) REFERENCES public.assistants(id,owner_id) ON DELETE RESTRICT,
  FOREIGN KEY(knowledge_index_id,assistant_id,owner_id)
    REFERENCES public.knowledge_indexes(id,assistant_id,owner_id) ON DELETE RESTRICT,
  CHECK(version>0), CHECK(state='published'),
  CHECK(source_count BETWEEN 0 AND 5),
  CHECK((source_count=0 AND knowledge_index_id IS NULL AND embedding_provider IS NULL
         AND embedding_model IS NULL AND vector_dimension IS NULL)
     OR (source_count>0 AND knowledge_index_id IS NOT NULL AND embedding_provider IS NOT NULL
         AND embedding_model IS NOT NULL AND vector_dimension=768)),
  CHECK(length(manifest_sha256)=64), CHECK(length(draft_fingerprint)=64),
  CHECK(retrieval_min_similarity IS NULL OR retrieval_min_similarity BETWEEN 0 AND 1),
  CHECK(activated_at IS NOT NULL)
);
CREATE INDEX ix_snapshot_owner_assistant ON public.published_snapshots(owner_id,assistant_id,version);
ALTER TABLE public.assistant_publications ADD CONSTRAINT fk_publication_active_snapshot
  FOREIGN KEY(active_snapshot_id,assistant_id,owner_id)
  REFERENCES public.published_snapshots(id,assistant_id,owner_id) ON DELETE RESTRICT;

CREATE TABLE public.published_sources (
  snapshot_id uuid NOT NULL, file_id uuid NOT NULL, assistant_id uuid NOT NULL, owner_id uuid NOT NULL,
  index_id uuid NOT NULL, source_sha256 varchar(64) NOT NULL, extraction_version varchar(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(snapshot_id,file_id),
  FOREIGN KEY(snapshot_id,assistant_id,owner_id)
    REFERENCES public.published_snapshots(id,assistant_id,owner_id) ON DELETE RESTRICT,
  FOREIGN KEY(index_id,assistant_id,owner_id)
    REFERENCES public.knowledge_indexes(id,assistant_id,owner_id) ON DELETE RESTRICT,
  FOREIGN KEY(index_id,file_id,assistant_id,owner_id)
    REFERENCES public.knowledge_index_sources(index_id,file_id,assistant_id,owner_id) ON DELETE RESTRICT,
  CHECK(length(source_sha256)=64)
);
CREATE INDEX ix_published_source_index ON public.published_sources(index_id,file_id);

CREATE TABLE public.publication_requests (
  id uuid PRIMARY KEY, assistant_id uuid NOT NULL, owner_id uuid NOT NULL,
  idempotency_key varchar(128) NOT NULL, request_sha256 varchar(64) NOT NULL,
  snapshot_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(assistant_id,owner_id,idempotency_key),
  FOREIGN KEY(assistant_id,owner_id) REFERENCES public.assistants(id,owner_id) ON DELETE RESTRICT,
  FOREIGN KEY(snapshot_id,assistant_id,owner_id)
    REFERENCES public.published_snapshots(id,assistant_id,owner_id) ON DELETE RESTRICT,
  CHECK(length(request_sha256)=64)
);

CREATE TABLE public.visitor_conversations (
  id uuid PRIMARY KEY, publication_id uuid NOT NULL, assistant_id uuid NOT NULL, owner_id uuid NOT NULL,
  token_sha256 varchar(64) NOT NULL, expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,publication_id,owner_id,assistant_id),
  FOREIGN KEY(publication_id,assistant_id,owner_id)
    REFERENCES public.assistant_publications(id,assistant_id,owner_id) ON DELETE RESTRICT,
  CHECK(length(token_sha256)=64), CHECK(expires_at > created_at AND expires_at <= created_at + interval '24 hours')
);
CREATE INDEX ix_visitor_conversation_owner ON public.visitor_conversations(owner_id,assistant_id,created_at DESC);

CREATE TABLE public.visitor_turns (
  id uuid PRIMARY KEY, conversation_id uuid NOT NULL, publication_id uuid NOT NULL,
  snapshot_id uuid NOT NULL, assistant_id uuid NOT NULL, owner_id uuid NOT NULL,
  request_id uuid NOT NULL, input_sha256 varchar(64) NOT NULL, user_text text NOT NULL,
  state varchar(16) NOT NULL DEFAULT 'pending', answer_text text, outcome varchar(16), error_code varchar(64),
  created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
  UNIQUE(conversation_id,request_id),
  FOREIGN KEY(conversation_id,publication_id,owner_id,assistant_id)
    REFERENCES public.visitor_conversations(id,publication_id,owner_id,assistant_id) ON DELETE RESTRICT,
  FOREIGN KEY(snapshot_id,assistant_id,owner_id)
    REFERENCES public.published_snapshots(id,assistant_id,owner_id) ON DELETE RESTRICT,
  CHECK(length(input_sha256)=64), CHECK(length(user_text) BETWEEN 1 AND 1000),
  CHECK(state IN ('pending','completed','fallback','failed','version_rejected','uncertain')),
  CHECK(outcome IS NULL OR outcome IN ('grounded','fallback')),
  CHECK((state='completed' AND answer_text IS NOT NULL AND outcome='grounded' AND completed_at IS NOT NULL)
     OR (state='fallback' AND answer_text IS NOT NULL AND outcome='fallback' AND completed_at IS NOT NULL)
     OR (state IN ('pending','failed','version_rejected','uncertain') AND answer_text IS NULL))
);
CREATE INDEX ix_visitor_turn_owner_history ON public.visitor_turns(owner_id,assistant_id,created_at,id);
""")

    # Protect all new public-schema tables from Data API/default grants; runtime access is explicit.
    for table in ("assistant_publications", "published_snapshots", "published_sources", "publication_requests", "visitor_conversations", "visitor_turns"):
        op.execute(f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC, anon, authenticated, service_role, assistant_runtime")
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON SCHEMA public FROM assistant_public_runtime")
    op.execute("GRANT USAGE ON SCHEMA public TO assistant_public_runtime")
    op.execute("""
GRANT SELECT,INSERT ON public.assistant_publications TO assistant_runtime;
GRANT UPDATE(active_snapshot_id,updated_at) ON public.assistant_publications TO assistant_runtime;
GRANT SELECT,INSERT ON public.published_snapshots,public.published_sources,public.publication_requests TO assistant_runtime;
GRANT SELECT(id,publication_id,assistant_id,owner_id,expires_at,created_at)
  ON public.visitor_conversations TO assistant_runtime;
GRANT SELECT(id,conversation_id,publication_id,snapshot_id,assistant_id,owner_id,request_id,input_sha256,user_text,state,answer_text,outcome,error_code,created_at,completed_at)
  ON public.visitor_turns TO assistant_runtime;
GRANT SELECT(id,owner_id,assistant_id,public_id,active_snapshot_id) ON public.assistant_publications TO assistant_public_runtime;
GRANT SELECT(id,assistant_id,owner_id,version,state,config,knowledge_index_id,embedding_provider,embedding_model,vector_dimension,retrieval_min_similarity,manifest_sha256,source_count,activated_at)
  ON public.published_snapshots TO assistant_public_runtime;
GRANT SELECT(snapshot_id,file_id,assistant_id,owner_id,index_id,source_sha256,extraction_version)
  ON public.published_sources TO assistant_public_runtime;
GRANT SELECT(id,index_id,owner_id,assistant_id,file_id,ordinal,extraction_version,chunker_version,source_sha256,start_offset,end_offset,token_count,text_sha256,chunk_text,embedding)
  ON public.knowledge_chunks TO assistant_public_runtime;
GRANT SELECT(id,publication_id,assistant_id,owner_id,expires_at,created_at),
  INSERT(id,publication_id,assistant_id,owner_id,token_sha256,expires_at,created_at)
  ON public.visitor_conversations TO assistant_public_runtime;
GRANT SELECT(id,conversation_id,publication_id,snapshot_id,assistant_id,owner_id,request_id,input_sha256,user_text,state,answer_text,outcome,error_code,created_at,completed_at),
  INSERT(id,conversation_id,publication_id,snapshot_id,assistant_id,owner_id,request_id,input_sha256,user_text,state,created_at),
  UPDATE(state,answer_text,outcome,error_code,completed_at)
  ON public.visitor_turns TO assistant_public_runtime;
""")
    # All policies fail closed if context is absent; malformed UUID context raises and aborts.
    for table in ("assistant_publications", "published_snapshots", "published_sources", "visitor_conversations", "visitor_turns"):
        owner = "owner_id=NULLIF(current_setting('app.owner_id',true),'')::uuid"
        op.execute(f"CREATE POLICY {table}_owner_select ON public.{table} FOR SELECT TO assistant_runtime USING ({owner})")
    op.execute("CREATE POLICY publication_owner_insert ON public.assistant_publications FOR INSERT TO assistant_runtime WITH CHECK (owner_id=NULLIF(current_setting('app.owner_id',true),'')::uuid)")
    op.execute("CREATE POLICY publication_owner_update ON public.assistant_publications FOR UPDATE TO assistant_runtime USING (owner_id=NULLIF(current_setting('app.owner_id',true),'')::uuid) WITH CHECK (owner_id=NULLIF(current_setting('app.owner_id',true),'')::uuid)")
    op.execute("CREATE POLICY snapshot_owner_insert ON public.published_snapshots FOR INSERT TO assistant_runtime WITH CHECK (owner_id=NULLIF(current_setting('app.owner_id',true),'')::uuid AND state='published')")
    op.execute("CREATE POLICY source_owner_insert ON public.published_sources FOR INSERT TO assistant_runtime WITH CHECK (owner_id=NULLIF(current_setting('app.owner_id',true),'')::uuid)")
    # INSERT .. RETURNING in the idempotency path also requires a matching SELECT policy.
    op.execute("CREATE POLICY request_owner_select ON public.publication_requests FOR SELECT TO assistant_runtime USING (owner_id=NULLIF(current_setting('app.owner_id',true),'')::uuid)")
    op.execute("CREATE POLICY request_owner_insert ON public.publication_requests FOR INSERT TO assistant_runtime WITH CHECK (owner_id=NULLIF(current_setting('app.owner_id',true),'')::uuid)")
    op.execute("""
CREATE POLICY publication_public_select ON public.assistant_publications FOR SELECT TO assistant_public_runtime
 USING (public_id=NULLIF(current_setting('app.public_id',true),'')::uuid AND active_snapshot_id IS NOT NULL);
""")
    op.execute("""
CREATE POLICY snapshot_public_select ON public.published_snapshots FOR SELECT TO assistant_public_runtime
 USING (id=NULLIF(current_setting('app.snapshot_id',true),'')::uuid AND state='published'
   AND EXISTS (SELECT 1 FROM public.assistant_publications p
     WHERE p.public_id=NULLIF(current_setting('app.public_id',true),'')::uuid
       AND p.active_snapshot_id=published_snapshots.id
       AND p.assistant_id=published_snapshots.assistant_id AND p.owner_id=published_snapshots.owner_id));
CREATE POLICY source_public_select ON public.published_sources FOR SELECT TO assistant_public_runtime
 USING (snapshot_id=NULLIF(current_setting('app.snapshot_id',true),'')::uuid
   AND EXISTS (SELECT 1 FROM public.published_snapshots s WHERE s.id=published_sources.snapshot_id));
CREATE POLICY conversation_public_select ON public.visitor_conversations FOR SELECT TO assistant_public_runtime
 USING (id=NULLIF(current_setting('app.conversation_id',true),'')::uuid
   AND token_sha256=NULLIF(current_setting('app.visitor_token_digest',true),'')
   AND expires_at>transaction_timestamp()
   AND EXISTS (SELECT 1 FROM public.assistant_publications p WHERE p.id=visitor_conversations.publication_id
     AND p.public_id=NULLIF(current_setting('app.public_id',true),'')::uuid));
CREATE POLICY conversation_public_insert ON public.visitor_conversations FOR INSERT TO assistant_public_runtime
 WITH CHECK (id=NULLIF(current_setting('app.conversation_id',true),'')::uuid
   AND token_sha256=NULLIF(current_setting('app.visitor_token_digest',true),'')
   AND expires_at>transaction_timestamp() AND expires_at<=transaction_timestamp()+interval '24 hours'
   AND EXISTS (SELECT 1 FROM public.assistant_publications p WHERE p.id=publication_id
     AND p.public_id=NULLIF(current_setting('app.public_id',true),'')::uuid AND p.active_snapshot_id IS NOT NULL));
CREATE POLICY turn_public_select ON public.visitor_turns FOR SELECT TO assistant_public_runtime
 USING (EXISTS (SELECT 1 FROM public.visitor_conversations c WHERE c.id=visitor_turns.conversation_id));
CREATE POLICY turn_public_insert ON public.visitor_turns FOR INSERT TO assistant_public_runtime
 WITH CHECK (state='pending' AND answer_text IS NULL
   AND snapshot_id=NULLIF(current_setting('app.snapshot_id',true),'')::uuid
   AND conversation_id=NULLIF(current_setting('app.conversation_id',true),'')::uuid
   AND EXISTS (SELECT 1 FROM public.visitor_conversations c WHERE c.id=conversation_id)
   AND EXISTS (SELECT 1 FROM public.published_snapshots s WHERE s.id=snapshot_id));
CREATE POLICY turn_public_update ON public.visitor_turns FOR UPDATE TO assistant_public_runtime
 USING (EXISTS (SELECT 1 FROM public.visitor_conversations c WHERE c.id=visitor_turns.conversation_id)
   AND state='pending')
 WITH CHECK (state IN ('completed','fallback','failed','version_rejected','uncertain'));
""")
    op.execute("""
CREATE POLICY chunk_public_select ON public.knowledge_chunks FOR SELECT TO assistant_public_runtime
 USING (EXISTS (SELECT 1 FROM public.published_sources r
    WHERE r.index_id=knowledge_chunks.index_id AND r.file_id=knowledge_chunks.file_id
      AND r.snapshot_id=NULLIF(current_setting('app.snapshot_id',true),'')::uuid
      AND r.assistant_id=knowledge_chunks.assistant_id AND r.owner_id=knowledge_chunks.owner_id));
""")
    # Snapshot and source records are immutable except a single activation/retention transition.
    op.execute("""
CREATE FUNCTION public.guard_published_snapshot() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$ BEGIN
  IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'published snapshots are immutable'; END IF;
  NEW.build_xid:=txid_current();
  IF NEW.state<>'published' OR NEW.activated_at IS NULL THEN RAISE EXCEPTION 'snapshot must be sealed at creation'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_guard_published_snapshot BEFORE INSERT OR UPDATE OR DELETE ON public.published_snapshots
 FOR EACH ROW EXECUTE FUNCTION public.guard_published_snapshot();
CREATE FUNCTION public.validate_published_manifest() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$ DECLARE sid uuid; expected_count integer; index_id uuid; manifest text; actual_count bigint; aid uuid; oid uuid; BEGIN
  IF TG_TABLE_NAME='published_snapshots' THEN sid:=NEW.id; aid:=NEW.assistant_id; oid:=NEW.owner_id;
  ELSE sid:=NEW.snapshot_id; END IF;
  SELECT source_count,knowledge_index_id,manifest_sha256,assistant_id,owner_id
    INTO expected_count,index_id,manifest,aid,oid FROM public.published_snapshots WHERE id=sid;
  IF NOT FOUND THEN RAISE EXCEPTION 'published snapshot is missing'; END IF;
  SELECT count(*) INTO actual_count FROM public.published_sources WHERE snapshot_id=sid;
  IF actual_count<>expected_count THEN RAISE EXCEPTION 'published source manifest is incomplete'; END IF;
  IF expected_count>0 AND (NOT EXISTS (SELECT 1 FROM public.knowledge_indexes i
      JOIN public.assistants a ON a.id=i.assistant_id AND a.owner_id=i.owner_id
      WHERE i.id=index_id AND i.assistant_id=aid AND i.owner_id=oid
        AND i.state='ready' AND i.completed_chunks=i.total_chunks AND a.active_knowledge_index_id=i.id)
      OR (SELECT manifest_sha256 FROM public.knowledge_indexes WHERE id=index_id) IS DISTINCT FROM manifest) THEN
    RAISE EXCEPTION 'published index must be current, complete, ready and match its manifest';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER trg_validate_snapshot_manifest AFTER INSERT ON public.published_snapshots
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.validate_published_manifest();
CREATE FUNCTION public.guard_published_source() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$ DECLARE snap_state text; snap_index uuid; BEGIN
  IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'published source references are immutable'; END IF;
  SELECT state,knowledge_index_id INTO snap_state,snap_index FROM public.published_snapshots WHERE id=NEW.snapshot_id AND build_xid=txid_current();
  IF snap_state IS DISTINCT FROM 'published' OR snap_index IS DISTINCT FROM NEW.index_id THEN RAISE EXCEPTION 'snapshot is sealed or source index differs'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.knowledge_index_sources s WHERE s.index_id=NEW.index_id
       AND s.file_id=NEW.file_id AND s.assistant_id=NEW.assistant_id AND s.owner_id=NEW.owner_id
       AND s.source_sha256=NEW.source_sha256 AND s.extraction_version=NEW.extraction_version) THEN
    RAISE EXCEPTION 'published source differs from immutable indexed source';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_guard_published_source BEFORE INSERT OR UPDATE OR DELETE ON public.published_sources
 FOR EACH ROW EXECUTE FUNCTION public.guard_published_source();
CREATE CONSTRAINT TRIGGER trg_validate_source_manifest AFTER INSERT ON public.published_sources
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.validate_published_manifest();
CREATE FUNCTION public.guard_publication_pointer() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$ BEGIN
  IF NEW.active_snapshot_id IS DISTINCT FROM OLD.active_snapshot_id AND NEW.active_snapshot_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM public.published_snapshots s WHERE s.id=NEW.active_snapshot_id
      AND s.assistant_id=NEW.assistant_id AND s.owner_id=NEW.owner_id AND s.state='published') THEN
    RAISE EXCEPTION 'active pointer must reference an active matching snapshot';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_guard_publication_pointer BEFORE UPDATE OF active_snapshot_id
 ON public.assistant_publications FOR EACH ROW EXECUTE FUNCTION public.guard_publication_pointer();
CREATE FUNCTION public.guard_visitor_conversation() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$ BEGIN
  IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'visitor conversation identity is immutable'; END IF;
  NEW.created_at:=transaction_timestamp();
  NEW.expires_at:=transaction_timestamp()+interval '24 hours';
  IF NEW.token_sha256 IS DISTINCT FROM current_setting('app.visitor_token_digest',true)
     OR NEW.id IS DISTINCT FROM NULLIF(current_setting('app.conversation_id',true),'')::uuid
     OR NEW.publication_id IS DISTINCT FROM (SELECT p.id FROM public.assistant_publications p
       WHERE p.public_id=NULLIF(current_setting('app.public_id',true),'')::uuid AND p.active_snapshot_id IS NOT NULL) THEN
    RAISE EXCEPTION 'visitor conversation scope is invalid';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_guard_visitor_conversation BEFORE INSERT OR UPDATE OR DELETE
 ON public.visitor_conversations FOR EACH ROW EXECUTE FUNCTION public.guard_visitor_conversation();
CREATE FUNCTION public.guard_visitor_turn() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$ BEGIN
  IF TG_OP<>'UPDATE' OR OLD.state<>'pending' OR
     (NEW.id,NEW.conversation_id,NEW.publication_id,NEW.snapshot_id,NEW.assistant_id,NEW.owner_id,
      NEW.request_id,NEW.input_sha256,NEW.user_text,NEW.created_at)
     IS DISTINCT FROM
     (OLD.id,OLD.conversation_id,OLD.publication_id,OLD.snapshot_id,OLD.assistant_id,OLD.owner_id,
      OLD.request_id,OLD.input_sha256,OLD.user_text,OLD.created_at) THEN
    RAISE EXCEPTION 'visitor turn identity/content is immutable';
  END IF;
  IF NEW.state IN ('completed','fallback') AND NOT EXISTS (
      SELECT 1 FROM public.assistant_publications p WHERE p.id=NEW.publication_id
       AND p.active_snapshot_id=NEW.snapshot_id) THEN
    RAISE EXCEPTION 'published version changed during response';
  END IF;
  IF NEW.state='version_rejected' AND NEW.answer_text IS NOT NULL THEN
    RAISE EXCEPTION 'rejected version cannot store generated answer';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_guard_visitor_turn BEFORE UPDATE OR DELETE ON public.visitor_turns
 FOR EACH ROW EXECUTE FUNCTION public.guard_visitor_turn();
""")

    # Private, cross-operation ledger. Runtime roles receive function EXECUTE only.
    op.execute("CREATE SCHEMA ai_accounting")
    op.execute("REVOKE ALL ON SCHEMA ai_accounting FROM PUBLIC,anon,authenticated,service_role,assistant_runtime,assistant_public_runtime")
    op.execute("GRANT USAGE ON SCHEMA ai_accounting TO assistant_budget_executor,assistant_runtime,assistant_public_runtime")
    op.execute("""
CREATE TABLE ai_accounting.price_versions (
 id uuid PRIMARY KEY, provider text NOT NULL, model text NOT NULL, input_microusd_per_million bigint NOT NULL,
 output_microusd_per_million bigint NOT NULL, embedding_microusd_per_million bigint NOT NULL,
 message_cap_microusd bigint NOT NULL, index_cap_microusd bigint NOT NULL,
 daily_cap_microusd bigint NOT NULL, valid_from timestamptz NOT NULL, valid_until timestamptz,
 CHECK(input_microusd_per_million>=0 AND output_microusd_per_million>=0 AND embedding_microusd_per_million>=0),
 CHECK(message_cap_microusd=10000 AND index_cap_microusd=100000 AND daily_cap_microusd=1000000),
 CHECK(valid_until IS NULL OR valid_until>valid_from)
);
CREATE TABLE ai_accounting.budget_days (
 day_utc date PRIMARY KEY, held_microusd bigint NOT NULL DEFAULT 0, charged_microusd bigint NOT NULL DEFAULT 0,
 CHECK(held_microusd>=0 AND charged_microusd>=0)
);
CREATE TABLE ai_accounting.budget_operations (
 id uuid PRIMARY KEY, caller_role name NOT NULL, scope_sha256 text NOT NULL, kind text NOT NULL,
 price_version uuid NOT NULL REFERENCES ai_accounting.price_versions(id), operation_cap_microusd bigint NOT NULL,
 held_microusd bigint NOT NULL DEFAULT 0, charged_microusd bigint NOT NULL DEFAULT 0,
 state text NOT NULL DEFAULT 'open', created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(id,caller_role,scope_sha256), CHECK(length(scope_sha256)=64),
 CHECK(kind IN ('index','playground_message','public_message')),
 CHECK(state IN ('open','closed','uncertain')),
 CHECK(held_microusd>=0 AND charged_microusd>=0)
);
CREATE TABLE ai_accounting.budget_attempts (
 id uuid PRIMARY KEY, operation_id uuid NOT NULL, caller_role name NOT NULL, scope_sha256 text NOT NULL,
 price_version uuid NOT NULL REFERENCES ai_accounting.price_versions(id), request_sha256 text NOT NULL,
 kind text NOT NULL, model text NOT NULL, max_input_tokens integer NOT NULL, max_output_tokens integer NOT NULL,
 held_microusd bigint NOT NULL, charged_microusd bigint,
 state text NOT NULL DEFAULT 'reserved', created_at timestamptz NOT NULL DEFAULT now(),
 dispatched_at timestamptz, settled_at timestamptz, input_tokens integer, output_tokens integer,
 UNIQUE(operation_id,id), UNIQUE(operation_id,request_sha256),
 FOREIGN KEY(operation_id,caller_role,scope_sha256)
   REFERENCES ai_accounting.budget_operations(id,caller_role,scope_sha256),
 CHECK(length(scope_sha256)=64 AND length(request_sha256)=64),
 CHECK(kind IN ('index_embedding','playground_embedding','playground_generation','public_embedding','public_generation')),
 CHECK(max_input_tokens BETWEEN 0 AND 100000 AND max_output_tokens BETWEEN 0 AND 8192),
 CHECK(held_microusd>=0 AND (charged_microusd IS NULL OR charged_microusd>=0)),
 CHECK(state IN ('reserved','dispatched','settled','uncertain','cancelled'))
);
CREATE TABLE ai_accounting.budget_day_holds (
 attempt_id uuid NOT NULL REFERENCES ai_accounting.budget_attempts(id), day_utc date NOT NULL REFERENCES ai_accounting.budget_days(day_utc),
 held_microusd bigint NOT NULL CHECK(held_microusd>=0), charged_microusd bigint NOT NULL DEFAULT 0 CHECK(charged_microusd>=0),
 PRIMARY KEY(attempt_id,day_utc)
);
""")
    for table in ("price_versions","budget_days","budget_operations","budget_attempts","budget_day_holds"):
        op.execute(f"ALTER TABLE ai_accounting.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE ai_accounting.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_executor_all ON ai_accounting.{table} TO assistant_budget_executor USING (true) WITH CHECK (true)")
    op.execute("""
GRANT USAGE ON SCHEMA ai_accounting TO assistant_budget_executor;
GRANT SELECT ON ai_accounting.price_versions TO assistant_budget_executor;
GRANT SELECT,INSERT ON ai_accounting.budget_days,ai_accounting.budget_operations,ai_accounting.budget_attempts,ai_accounting.budget_day_holds TO assistant_budget_executor;
GRANT UPDATE(held_microusd,charged_microusd) ON ai_accounting.budget_days TO assistant_budget_executor;
GRANT UPDATE(held_microusd,charged_microusd,state) ON ai_accounting.budget_operations TO assistant_budget_executor;
GRANT UPDATE(state,dispatched_at,settled_at,input_tokens,output_tokens,charged_microusd) ON ai_accounting.budget_attempts TO assistant_budget_executor;
GRANT UPDATE(held_microusd,charged_microusd) ON ai_accounting.budget_day_holds TO assistant_budget_executor;
""")
    # Functions are SECURITY DEFINER, owned by a NOLOGIN role with no tenant-table grants.
    op.execute("""
CREATE FUNCTION ai_accounting.reserve_attempt(operation_id uuid,attempt_id uuid,kind text,scope_sha256 text,
 price_version uuid,max_input_tokens bigint,max_output_tokens bigint,request_sha256 text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE caller name:=session_user; scope text; op_kind text; op_cap bigint; op_state text; model_name text; input_price bigint; output_price bigint;
DECLARE embed_price bigint; daily_cap bigint; hold bigint; provider_name text; expected_provider text;
DECLARE today date:=timezone('utc',transaction_timestamp())::date;
DECLARE d date; existing ai_accounting.budget_attempts%ROWTYPE;
BEGIN
 IF caller NOT IN ('assistant_runtime','assistant_public_runtime') OR length(request_sha256)<>64
    OR length(scope_sha256)<>64 OR max_input_tokens<0 OR max_input_tokens>100000
    OR max_output_tokens<0 OR max_output_tokens>8192 THEN RETURN false; END IF;
 IF caller='assistant_runtime' AND kind NOT IN ('index_embedding','playground_embedding','playground_generation') THEN RETURN false; END IF;
 IF caller='assistant_public_runtime' AND kind NOT IN ('public_embedding','public_generation') THEN RETURN false; END IF;
 IF caller='assistant_runtime' THEN
   scope:=encode(sha256(convert_to(current_setting('app.owner_id',true)||':'||current_setting('app.assistant_id',true),'UTF8')),'hex');
 ELSE
   scope:=encode(sha256(convert_to(current_setting('app.public_id',true)||':'||current_setting('app.conversation_id',true)||':'||current_setting('app.visitor_token_digest',true),'UTF8')),'hex');
 END IF;
 IF scope IS NULL OR scope<>scope_sha256 THEN RETURN false; END IF;
 SELECT * INTO existing FROM ai_accounting.budget_attempts a WHERE a.id=attempt_id FOR UPDATE;
 IF FOUND THEN RETURN existing.operation_id=reserve_attempt.operation_id AND existing.caller_role=caller
   AND existing.scope_sha256=scope AND existing.request_sha256=request_sha256 AND existing.state='reserved'; END IF;
 SELECT o.kind,o.operation_cap_microusd,o.state INTO op_kind,op_cap,op_state FROM ai_accounting.budget_operations o
   WHERE o.id=operation_id AND o.caller_role=caller AND o.scope_sha256=scope AND o.price_version=reserve_attempt.price_version FOR UPDATE;
 IF NOT FOUND THEN
   IF kind IN ('index_embedding') THEN op_kind:='index'; op_cap:=100000;
   ELSE op_kind:=CASE WHEN kind IN ('public_embedding','public_generation') THEN 'public_message' ELSE 'playground_message' END; op_cap:=10000; END IF;
   INSERT INTO ai_accounting.budget_operations(id,caller_role,scope_sha256,kind,price_version,operation_cap_microusd)
     VALUES(operation_id,caller,scope,op_kind,price_version,op_cap) ON CONFLICT DO NOTHING;
   SELECT o.operation_cap_microusd,o.state INTO op_cap,op_state FROM ai_accounting.budget_operations o WHERE o.id=operation_id
     AND o.caller_role=caller AND o.scope_sha256=scope AND o.kind=op_kind AND o.price_version=reserve_attempt.price_version FOR UPDATE;
   IF NOT FOUND THEN RETURN false; END IF;
 END IF;
 IF op_state<>'open' THEN RETURN false; END IF;
 expected_provider:=CASE WHEN kind LIKE '%embedding' THEN 'openai' ELSE 'groq' END;
 SELECT provider,model,input_microusd_per_million,output_microusd_per_million,embedding_microusd_per_million,daily_cap_microusd
   INTO provider_name,model_name,input_price,output_price,embed_price,daily_cap FROM ai_accounting.price_versions p
   WHERE p.id=reserve_attempt.price_version
     AND p.provider=expected_provider
     AND p.valid_from<=transaction_timestamp() AND (p.valid_until IS NULL OR p.valid_until>transaction_timestamp());
 IF NOT FOUND THEN RETURN false; END IF;
 IF kind LIKE '%embedding' THEN hold:=ceil(max_input_tokens::numeric*embed_price/1000000)::bigint;
 ELSE hold:=ceil(max_input_tokens::numeric*input_price/1000000 + max_output_tokens::numeric*output_price/1000000)::bigint; END IF;
 IF hold<1 THEN hold:=1; END IF;
 IF (SELECT o.charged_microusd+o.held_microusd+hold>op_cap FROM ai_accounting.budget_operations o WHERE o.id=reserve_attempt.operation_id) THEN RETURN false; END IF;
 IF EXISTS (SELECT 1 FROM ai_accounting.budget_attempts a WHERE a.operation_id=reserve_attempt.operation_id
      AND a.state IN ('dispatched','uncertain')) THEN RETURN false; END IF;
 INSERT INTO ai_accounting.budget_attempts(id,operation_id,caller_role,scope_sha256,price_version,request_sha256,kind,model,max_input_tokens,max_output_tokens,held_microusd)
   VALUES(attempt_id,operation_id,caller,scope,price_version,request_sha256,kind,model_name,max_input_tokens,max_output_tokens,hold);
 UPDATE ai_accounting.budget_operations o SET held_microusd=o.held_microusd+hold WHERE o.id=reserve_attempt.operation_id;
 FOR d IN SELECT today UNION SELECT today+1 ORDER BY 1 LOOP
   INSERT INTO ai_accounting.budget_days(day_utc) VALUES(d) ON CONFLICT DO NOTHING;
   PERFORM 1 FROM ai_accounting.budget_days WHERE day_utc=d FOR UPDATE;
   IF (SELECT held_microusd+charged_microusd+hold>daily_cap FROM ai_accounting.budget_days WHERE day_utc=d) THEN
     RAISE EXCEPTION 'AI budget unavailable';
   END IF;
   UPDATE ai_accounting.budget_days SET held_microusd=held_microusd+hold WHERE day_utc=d;
   INSERT INTO ai_accounting.budget_day_holds(attempt_id,day_utc,held_microusd) VALUES(attempt_id,d,hold);
 END LOOP;
 RETURN true;
END $$;

CREATE FUNCTION ai_accounting.mark_dispatched(attempt_id uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$ DECLARE a ai_accounting.budget_attempts%ROWTYPE; scope text;
BEGIN
 IF session_user='assistant_runtime' THEN scope:=encode(sha256(convert_to(current_setting('app.owner_id',true)||':'||current_setting('app.assistant_id',true),'UTF8')),'hex');
 ELSIF session_user='assistant_public_runtime' THEN scope:=encode(sha256(convert_to(current_setting('app.public_id',true)||':'||current_setting('app.conversation_id',true)||':'||current_setting('app.visitor_token_digest',true),'UTF8')),'hex');
 ELSE RETURN false; END IF;
 SELECT * INTO a FROM ai_accounting.budget_attempts WHERE id=attempt_id FOR UPDATE;
 IF scope IS NULL OR NOT FOUND OR a.caller_role<>session_user OR a.scope_sha256<>scope OR a.state<>'reserved' THEN RETURN false; END IF;
 IF a.created_at < transaction_timestamp()-interval '60 seconds'
    OR NOT EXISTS (SELECT 1 FROM ai_accounting.budget_day_holds h WHERE h.attempt_id=a.id
       AND h.day_utc=timezone('utc',transaction_timestamp())::date AND h.held_microusd=a.held_microusd)
    OR NOT EXISTS (SELECT 1 FROM ai_accounting.budget_day_holds h WHERE h.attempt_id=a.id
       AND h.day_utc=timezone('utc',transaction_timestamp())::date+1 AND h.held_microusd=a.held_microusd) THEN RETURN false; END IF;
 UPDATE ai_accounting.budget_attempts SET state='dispatched',dispatched_at=transaction_timestamp() WHERE id=attempt_id;
 RETURN true; END $$;

CREATE FUNCTION ai_accounting.settle_attempt(attempt_id uuid,input_tokens bigint,output_tokens bigint)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE a ai_accounting.budget_attempts%ROWTYPE; cost bigint; ip bigint;op bigint;ep bigint; r record; scope text;
BEGIN
 IF session_user='assistant_runtime' THEN scope:=encode(sha256(convert_to(current_setting('app.owner_id',true)||':'||current_setting('app.assistant_id',true),'UTF8')),'hex');
 ELSIF session_user='assistant_public_runtime' THEN scope:=encode(sha256(convert_to(current_setting('app.public_id',true)||':'||current_setting('app.conversation_id',true)||':'||current_setting('app.visitor_token_digest',true),'UTF8')),'hex');
 ELSE RETURN false; END IF;
 SELECT * INTO a FROM ai_accounting.budget_attempts WHERE id=attempt_id FOR UPDATE;
 IF scope IS NULL OR NOT FOUND OR a.caller_role<>session_user OR a.scope_sha256<>scope
    OR input_tokens<0 OR output_tokens<0 OR input_tokens>a.max_input_tokens OR output_tokens>a.max_output_tokens THEN RETURN false; END IF;
 IF a.state='settled' THEN RETURN a.input_tokens=input_tokens AND a.output_tokens=output_tokens; END IF;
 IF a.state<>'dispatched' THEN RETURN false; END IF;
 SELECT input_microusd_per_million,output_microusd_per_million,embedding_microusd_per_million INTO ip,op,ep
   FROM ai_accounting.price_versions WHERE id=a.price_version;
 IF a.kind LIKE '%embedding' THEN cost:=ceil(input_tokens::numeric*ep/1000000)::bigint;
 ELSE cost:=ceil(input_tokens::numeric*ip/1000000+output_tokens::numeric*op/1000000)::bigint; END IF;
 IF cost>a.held_microusd THEN RETURN false; END IF;
 UPDATE ai_accounting.budget_attempts SET state='settled',input_tokens=settle_attempt.input_tokens,output_tokens=settle_attempt.output_tokens,
   charged_microusd=cost,settled_at=transaction_timestamp() WHERE id=attempt_id;
 UPDATE ai_accounting.budget_operations SET held_microusd=held_microusd-a.held_microusd+cost,
   charged_microusd=charged_microusd+cost WHERE id=a.operation_id;
 FOR r IN SELECT * FROM ai_accounting.budget_day_holds WHERE budget_day_holds.attempt_id=settle_attempt.attempt_id ORDER BY day_utc FOR UPDATE LOOP
   UPDATE ai_accounting.budget_days SET held_microusd=held_microusd-r.held_microusd,
     charged_microusd=charged_microusd+cost WHERE day_utc=r.day_utc;
   UPDATE ai_accounting.budget_day_holds SET held_microusd=0,charged_microusd=cost
     WHERE budget_day_holds.attempt_id=settle_attempt.attempt_id AND day_utc=r.day_utc;
 END LOOP;
 RETURN true; END $$;

CREATE FUNCTION ai_accounting.cancel_undispatched(attempt_id uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$ DECLARE a ai_accounting.budget_attempts%ROWTYPE; r record; scope text;
BEGIN
 IF session_user='assistant_runtime' THEN scope:=encode(sha256(convert_to(current_setting('app.owner_id',true)||':'||current_setting('app.assistant_id',true),'UTF8')),'hex');
 ELSIF session_user='assistant_public_runtime' THEN scope:=encode(sha256(convert_to(current_setting('app.public_id',true)||':'||current_setting('app.conversation_id',true)||':'||current_setting('app.visitor_token_digest',true),'UTF8')),'hex');
 ELSE RETURN false; END IF;
 SELECT * INTO a FROM ai_accounting.budget_attempts WHERE id=attempt_id FOR UPDATE;
 IF scope IS NULL OR NOT FOUND OR a.caller_role<>session_user OR a.scope_sha256<>scope OR a.state<>'reserved' THEN RETURN false; END IF;
 UPDATE ai_accounting.budget_attempts SET state='cancelled' WHERE id=attempt_id;
 UPDATE ai_accounting.budget_operations SET held_microusd=held_microusd-a.held_microusd WHERE id=a.operation_id;
 FOR r IN SELECT * FROM ai_accounting.budget_day_holds WHERE budget_day_holds.attempt_id=cancel_undispatched.attempt_id FOR UPDATE LOOP
   UPDATE ai_accounting.budget_days SET held_microusd=held_microusd-r.held_microusd WHERE day_utc=r.day_utc;
   UPDATE ai_accounting.budget_day_holds SET held_microusd=0 WHERE budget_day_holds.attempt_id=cancel_undispatched.attempt_id AND day_utc=r.day_utc;
 END LOOP;
 RETURN true; END $$;
""")
    # PostgreSQL requires the migration principal to be able to SET ROLE to the
    # new owner, and the new owner to have CREATE on the function schema. Keep
    # both grants scoped to this transfer and revoke them on success or failure.
    # The exception subtransaction also rolls back any partial ownership changes.
    op.execute("""
DO $$ DECLARE function_signature text; BEGIN
  BEGIN
    EXECUTE format('GRANT assistant_budget_executor TO %I', current_user);
    GRANT CREATE ON SCHEMA ai_accounting TO assistant_budget_executor;
    FOREACH function_signature IN ARRAY ARRAY[
      'reserve_attempt(uuid,uuid,text,text,uuid,bigint,bigint,text)',
      'mark_dispatched(uuid)',
      'settle_attempt(uuid,bigint,bigint)',
      'cancel_undispatched(uuid)'
    ] LOOP
      EXECUTE format('ALTER FUNCTION ai_accounting.%s OWNER TO assistant_budget_executor', function_signature);
    END LOOP;
  EXCEPTION WHEN OTHERS THEN
    EXECUTE 'REVOKE CREATE ON SCHEMA ai_accounting FROM assistant_budget_executor';
    EXECUTE format('REVOKE assistant_budget_executor FROM %I', current_user);
    RAISE;
  END;
END $$
""")
    # Only the function owner may change the function ACL. Temporarily SET ROLE
    # to the new owner, revoke PostgreSQL's default PUBLIC EXECUTE, and grant
    # EXECUTE only to the two approved runtime roles.
    # Alembic runs this revision in one transaction; any failure here rolls back
    # the ownership transfers, temporary grants, and SET ROLE state together.
    op.execute("SET ROLE assistant_budget_executor")
    for function in (
        "reserve_attempt(uuid,uuid,text,text,uuid,bigint,bigint,text)",
        "mark_dispatched(uuid)", "settle_attempt(uuid,bigint,bigint)", "cancel_undispatched(uuid)"):
        op.execute(f"REVOKE ALL ON FUNCTION ai_accounting.{function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION ai_accounting.{function} TO assistant_runtime,assistant_public_runtime")
    op.execute("RESET ROLE")
    op.execute("""
DO $$ BEGIN
  REVOKE CREATE ON SCHEMA ai_accounting FROM assistant_budget_executor;
  EXECUTE format('REVOKE assistant_budget_executor FROM %I', current_user);
END $$
""")
    op.execute("""
DO $$ BEGIN
  -- PostgreSQL gives a CREATEROLE creator an ADMIN-only membership in roles it
  -- creates. That grant has SET/INHERIT disabled and is not the temporary
  -- membership used below. Permit only that inert creator membership; no other
  -- role may inherit or SET ROLE to the executor.
  IF EXISTS (SELECT FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid
      JOIN pg_roles u ON u.oid=m.member
      WHERE r.rolname='assistant_budget_executor'
        AND (u.rolname <> current_user OR NOT m.admin_option OR m.inherit_option OR m.set_option))
     OR EXISTS (SELECT FROM pg_auth_members m JOIN pg_roles u ON u.oid=m.member
      WHERE u.rolname='assistant_budget_executor') THEN
    RAISE EXCEPTION 'Unexpected effective membership on assistant_budget_executor';
  END IF;
  IF has_schema_privilege('assistant_budget_executor','ai_accounting','CREATE') THEN
    RAISE EXCEPTION 'Temporary accounting-schema CREATE privilege was not revoked';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='assistant_budget_executor'
      AND NOT rolcanlogin AND NOT rolsuper AND NOT rolbypassrls AND NOT rolinherit
      AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication) THEN
    RAISE EXCEPTION 'Budget executor role attributes differ from approved baseline';
  END IF;
  IF EXISTS (SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname='ai_accounting'
        AND p.proname IN ('reserve_attempt','mark_dispatched','settle_attempt','cancel_undispatched')
        AND p.proowner <> 'assistant_budget_executor'::regrole) THEN
    RAISE EXCEPTION 'A budget SECURITY DEFINER function has an unexpected owner';
  END IF;
  IF EXISTS (SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) acl
      WHERE n.nspname='ai_accounting'
        AND p.proname IN ('reserve_attempt','mark_dispatched','settle_attempt','cancel_undispatched')
        AND acl.grantee=0 AND acl.privilege_type='EXECUTE')
     OR EXISTS (SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname='ai_accounting'
        AND p.proname IN ('reserve_attempt','mark_dispatched','settle_attempt','cancel_undispatched')
        AND (NOT has_function_privilege('assistant_runtime',p.oid,'EXECUTE')
          OR NOT has_function_privilege('assistant_public_runtime',p.oid,'EXECUTE'))) THEN
    RAISE EXCEPTION 'Budget function EXECUTE grants differ from the approved runtime boundary';
  END IF;
END $$
""")
    # Remove default EXECUTE on the non-definer trigger helpers as well.
    for function in ("guard_published_snapshot()", "validate_published_manifest()", "guard_published_source()", "guard_publication_pointer()", "guard_visitor_conversation()", "guard_visitor_turn()"):
        op.execute(f"REVOKE ALL ON FUNCTION public.{function} FROM PUBLIC,anon,authenticated,service_role,assistant_runtime,assistant_public_runtime")

    op.execute("""
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['price_versions','budget_days','budget_operations','budget_attempts','budget_day_holds'] LOOP
   EXECUTE format('REVOKE ALL ON TABLE ai_accounting.%I FROM PUBLIC,anon,authenticated,service_role,assistant_runtime,assistant_public_runtime',t);
 END LOOP;
END $$;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA ai_accounting FROM PUBLIC,assistant_runtime,assistant_public_runtime,assistant_budget_executor;
""")


def downgrade():
    raise RuntimeError("Published snapshots, visitor history and accounting state require reviewed non-destructive rollback")
