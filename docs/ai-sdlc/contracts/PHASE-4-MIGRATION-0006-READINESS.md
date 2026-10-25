# Phase 4 Migration 0006 Readiness Review

Review date: 2026-10-24

Read-only live preflight follow-up: 2026-10-26

## Status

Migration `0006_publication_budget` is corrected and verified in a disposable
local PostgreSQL environment. No live Supabase connection or change was made by
this review. Recommendation: **conditional GO for a separately authorized live
preflight and migration**, not authorization to apply it.

## Root cause and correction

PostgreSQL requires the migration role to be able to `SET ROLE` to a new function
owner, and the new owner must have `CREATE` on the function's schema before
`ALTER FUNCTION ... OWNER TO` succeeds. The migration now grants the migration
role temporary membership in `assistant_budget_executor` and grants that role
temporary `CREATE` on `ai_accounting`. It transfers the four accounting
functions, then uses `SET ROLE assistant_budget_executor` to remove default
`PUBLIC EXECUTE` and grant `EXECUTE` only to `assistant_runtime` and
`assistant_public_runtime`. It resets the role and revokes the temporary
membership and schema privilege.

The ownership-transfer block revokes temporary grants before re-raising any
failure. The full Alembic revision uses transactional DDL; a later failure rolls
back role grants, ownership changes, ACL changes, and transaction-local role
state. Postconditions fail the migration if function owners, role attributes,
function EXECUTE grants, or the temporary schema privilege differ from the
approved boundary.

PostgreSQL automatically gives a non-superuser `CREATEROLE` role ADMIN OPTION
on roles it creates. The local database therefore retained one creator
membership for `phase4_migrator` with `ADMIN=true`, `SET=false`, and
`INHERIT=false`. This is distinct from the temporary SET membership, which was
revoked. No application runtime role is a member of the executor. The migration
principal is already a privileged deployment identity and must remain trusted.

## Local verification evidence

- A clean `pgvector/pg16` container was used without a persistent volume. The
  test role was non-superuser with `CREATEROLE`, `CREATEDB`, and
  `BYPASSRLS`, and owned the disposable database and `public` schema. Supabase
  compatibility roles and `assistant_runtime` were provisioned only in that
  container.
- Alembic successfully applied revisions through `0005_batch_idem_grant`, then
  applied `0006_publication_budget` using the non-superuser migration role.
- Read-only post-migration checks reported revision `0006_publication_budget`,
  all four accounting functions owned by `assistant_budget_executor`, and the
  executor as `NOLOGIN`, `NOSUPERUSER`, `NOBYPASSRLS`, and without role-creation
  or database-creation attributes.
- `assistant_budget_executor` retained `USAGE` but not `CREATE` on
  `ai_accounting`. No role had effective `SET` or inherited membership in the
  executor. The four functions had no `PUBLIC EXECUTE`; both approved runtime
  roles had execute permission.
- All five accounting tables had enabled and forced RLS with five policies.
  All six publication/conversation tables and the existing `knowledge_chunks`
  table retained enabled and forced RLS. Neither runtime role had `DELETE` on
  accounting tables. The public runtime had no `CREATE` on `public`.
- Existing Phase 4 PostgreSQL regression module: **11 passed**.
- Focused offline migration SQL suite: **6 passed**.
- Full offline backend suite: **459 passed, 39 skipped**. The 39 skips are
  opt-in PostgreSQL integration tests; the P4 PostgreSQL module was run separately.
- No AI provider calls, Supabase access, deployment, commit, or push occurred.

The disposable test database contained no pre-existing business records. Data
preservation was therefore reviewed from the migration SQL: it creates the
Phase 4 publication/accounting objects and adds a read policy and `SELECT` grant
for `knowledge_chunks`; it does not insert, update, delete, truncate, or drop
rows/tables in existing assistant, knowledge-file, extracted-text, or embedding
tables.

## Live prerequisites before a separately approved execution

Repeat read-only checks immediately before migration and stop on any mismatch:

1. Alembic revision is exactly `0005_batch_idem_grant`.
2. `assistant_runtime` has the approved login and restricted role attributes;
   no unexpected membership exists.
3. `assistant_public_runtime`, `assistant_budget_executor`, Phase 4 tables, and
   `ai_accounting` do not already exist.
4. The migration identity is a non-superuser with `CREATEROLE`, can create in
   the target database/public schema and grant `USAGE` on public, owns or has
   sufficient grant authority over the existing `knowledge_chunks` table, and
   has `REFERENCES` authority on the existing FK targets.
5. The required Supabase roles (`anon`, `authenticated`, `service_role`) exist;
   `public.vector(768)` and the Phase 1-3 forced-RLS baseline remain intact.
6. The live PostgreSQL version supports the membership options used by the
   migration. Confirm the post-migration creator ADMIN membership and verify it
   has neither `SET` nor `INHERIT`; no runtime role may be a member of the
   executor.
7. A separately approved migration window and recovery plan are available.
   Downgrade intentionally raises; do not attempt a destructive rollback.

After a separately authorized migration, verify revision, function owners and
ACLs, executor role attributes/memberships, `ai_accounting` schema privileges,
forced RLS and policies, exact runtime grants (including no `DELETE`), and the
unchanged Phase 1-3 schema/data baseline. Do not enable public chat or budget
dispatch as part of applying this migration.

## Read-only live preflight follow-up (2026-10-26)

The authorized read-only preflight against the existing development Supabase
project found Alembic revision `0005_batch_idem_grant`, pgvector 0.8.2 installed
in `public` with `public.vector(768)` available, and the expected Phase 1-3
tables and forced-RLS policies. The four Phase 4 tables, `ai_accounting`,
`assistant_public_runtime`, `assistant_budget_executor`, and migration 0006
target functions were absent. The inspected migration role had the required
database/schema and existing-table authorities for this migration; the
existing `assistant_runtime` remained restricted and had no `DELETE` grants.
The previously reviewed `ensure_rls` event trigger and
`public.rls_auto_enable()` definition matched the approved baseline.

The migration file reviewed for that preflight is the same local working-tree
version described in the local PostgreSQL verification above; no migration or
database object was changed during preflight. The preflight was read-only and
does not itself authorize or apply the migration. Re-run the preflight
immediately before any separately approved execution.
