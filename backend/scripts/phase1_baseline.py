"""Only the exact auto-RLS objects reviewed and approved by the owner."""
from sqlalchemy import text

REVIEWED_DEFINITION = """CREATE OR REPLACE FUNCTION public.rls_auto_enable()
 RETURNS event_trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE
  cmd record;
  tbl name;
BEGIN
  FOR cmd IN
    SELECT *
    FROM pg_event_trigger_ddl_commands()
    WHERE command_tag IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')
      AND object_type IN ('table','partitioned table')
  LOOP
     IF cmd.schema_name IS NOT NULL AND cmd.schema_name IN ('public') AND cmd.schema_name NOT IN ('pg_catalog','information_schema') AND cmd.schema_name NOT LIKE 'pg_toast%' AND cmd.schema_name NOT LIKE 'pg_temp%' THEN
      BEGIN
        SELECT c.relname INTO tbl FROM pg_catalog.pg_class c WHERE c.oid = cmd.objid;
        EXECUTE format('alter table if exists %I.%I enable row level security', cmd.schema_name, tbl);
        RAISE LOG 'rls_auto_enable: enabled RLS on %', cmd.object_identity;
      EXCEPTION
        WHEN OTHERS THEN
          RAISE LOG 'rls_auto_enable: failed to enable RLS on %', cmd.object_identity;
      END;
     ELSE
        RAISE LOG 'rls_auto_enable: skip % (either system schema or not in enforced list: %.)', cmd.object_identity, cmd.schema_name;
     END IF;
  END LOOP;
END;
$function$
"""


def verify_baseline(connection):
    functions = connection.execute(text("""
        SELECT p.oid, p.proname, pg_get_userbyid(p.proowner) AS owner,
               p.prosecdef, p.proconfig, pg_get_functiondef(p.oid) AS definition
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND NOT EXISTS (
          SELECT FROM pg_depend d WHERE d.classid='pg_proc'::regclass
          AND d.objid=p.oid AND d.deptype='e')
    """)).mappings().all()
    if len(functions) != 1:
        raise RuntimeError("Public function baseline differs")
    function = functions[0]
    if (function['proname'] != 'rls_auto_enable' or function['owner'] != 'postgres'
        or function['prosecdef'] is not True or function['proconfig'] != ['search_path=pg_catalog']
        or function['definition'].strip() != REVIEWED_DEFINITION.strip()):
        raise RuntimeError("Reviewed auto-RLS function definition/configuration differs")
    triggers = connection.execute(text("""
        SELECT e.evtname, e.evtevent, e.evtenabled, e.evttags,
               pg_get_userbyid(e.evtowner) AS owner
        FROM pg_event_trigger e WHERE e.evtfoid=:oid
    """), {'oid':function['oid']}).mappings().all()
    if len(triggers) != 1:
        raise RuntimeError("Auto-RLS trigger baseline differs")
    trigger = triggers[0]
    if (trigger['evtname'] != 'ensure_rls' or trigger['evtevent'] != 'ddl_command_end'
        or trigger['evtenabled'] != 'O' or trigger['owner'] != 'postgres'
        or sorted(trigger['evttags']) != ['CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO']):
        raise RuntimeError("Reviewed auto-RLS trigger configuration differs")
