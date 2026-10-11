# Phase 1 owner isolation review

Status: design approved; deployed; database and authenticated-owner API verification complete

Live verification update (2026-10-11): restricted role and both revisions are now
deployed. Nine live verification groups passed, including two real Supabase Auth
owners and cleanup of the three current-run fixtures. No retained test records
remain. See PHASE-1-LIVE-RESULTS.json and the learning-report addendum. The setup steps below
describe the original deployment procedure, not instructions to rerun provisioning
on the now-deployed database.

## Approved implementation (supersedes the historical options below)

The human approved the trusted FastAPI identity boundary, separate runtime and
migration connections, assistant_runtime, transaction-local identity, no DELETE,
and FastAPI-only assistant access. No live database changes are authorized yet.

- FastAPI reads DATABASE_URL only. Alembic requires MIGRATION_DATABASE_URL only.
  Legacy host/user/password component fallback has been removed. The deployed
  FastAPI process must not receive the migration credential.
- The database dependency authenticates through the existing Supabase verifier
  before opening its owner transaction. It binds a validated UUID using
  set_config('app.owner_id', :owner_id, true) before yielding the Session.
- RLS compares owner_id against NULLIF(current_setting('app.owner_id', true), '')::uuid.
  Missing/empty identity exposes no rows and rejects inserts; malformed identity
  errors rather than granting access. Commit/rollback ends the local setting.
- The runtime login is not a table owner and has no privileged role memberships.
  Startup rejects an unexpected or privileged runtime role, disabled RLS, owner
  UPDATE, DELETE/TRUNCATE access, or public-schema CREATE access.
- Migration 0002 enables and forces RLS, explicitly defines SELECT/INSERT/UPDATE
  policies, and grants UPDATE only on name, role, colors, response_style, tone,
  fallback_message, updated_at. owner_id, id, state, created_at are not updateable.
- It revokes table AND column grants from PUBLIC, anon, authenticated and the
  runtime role before granting the exact runtime permissions. It does not change
  Supabase Auth, auth schema, system roles, or project-wide Data API settings.
  Existing policies cause migration failure for review rather than silent override.
- Data API exposure was reviewed in source only. Live grants, inherited privileges,
  existing RPCs/views and project settings still need an authorized environment audit.
- The custom setting is a trusted application assertion, NOT a database-verified
  authentication claim. Arbitrary SQL with runtime credentials can impersonate
  another owner by changing it. This protects against missing owner filters, not
  runtime credential compromise or arbitrary SQL execution. No SECURITY DEFINER
  or database JWT verifier is introduced.

## Setup and validation runbook

### Limited migration-metadata correction (2026-10-11)

Read-only live preflight found no public tables or assistant_runtime role, but
default table grants included TRUNCATE for anon/authenticated. Revision 0002 now
also revokes table and column privileges on public.alembic_version from PUBLIC,
anon, authenticated, service_role, and assistant_runtime. It enables RLS without
API policies; the migration table owner retains Alembic access. This does not
change default privileges, Supabase Auth, or grants on unrelated objects.

Alembic explicitly uses public for its version table and a single transaction
across revisions. For first deployment use `upgrade head`, not separate committed
upgrades to 0001 then 0002. Metadata protection is in 0002; stopping at 0001 would
not include it. The offline SQL regression test verifies one BEGIN/COMMIT and
revocation before commit; it does not prove live PostgreSQL execution.

All URLs contain secrets and must stay outside Git and logs. Use psycopg URLs and
percent-encode reserved characters in credentials. Verify the actual current_user;
a pooler's connection username may contain an additional project suffix.

### Local disposable PostgreSQL only

1. Start a dedicated local PostgreSQL 15+ instance and create database
   assistant_builder_phase1_test. Do not forward localhost to a live database.
2. As its administrator run backend/scripts/provision_runtime_role.sql, and set
   the password separately with psql's interactive \password assistant_runtime.
   Create NOLOGIN stand-ins anon and authenticated for Data API grant tests.
   Ensure public schema CREATE is not inherited by the runtime login; if inherited,
   review the local schema ACL before proceeding. Do not copy broad ACL changes
   into Supabase.
3. Set PHASE1_LOCAL_PG_TESTS=1, PHASE1_LOCAL_MIGRATION_URL and
   PHASE1_LOCAL_RUNTIME_URL in the test process. Both URLs must use a loopback host,
   database assistant_builder_phase1_test, and no query overrides.
4. From backend run: python -m pytest tests/test_postgresql_phase1.py -q.
   This opt-in suite applies migrations to that dedicated local database and tests
   actual login credentials; it never reads connection URLs from developer .env.
   Administrative cleanup deletes only rows belonging to randomly generated test
   owners. Do not use migration credentials as the runtime URL.
5. The normal local suite skips PostgreSQL checks unless explicitly opted in.
   SQLite tests verify lifecycle only; they do not prove RLS behavior.

### Live Supabase steps requiring subsequent approval

1. Audit target project, migration/table ownership, existing assistant grants and
   policies, role memberships, exposed views/RPCs and pooler support. Obtain a
   recovery plan before applying schema/security changes.
2. Provision assistant_runtime via the reviewed script using an administrative
   connection; set its password privately. Do not grant privileged memberships.
3. Supply MIGRATION_DATABASE_URL to the migration process only. Review offline SQL
   with `uv run alembic upgrade head --sql`; then, only after explicit approval,
   run `uv run alembic upgrade head`. Role provisioning precedes migration 0002.
4. Set FastAPI DATABASE_URL to the restricted login and remove old component
   settings. Do not change credentials automatically or ship migration secrets
   with the server. Restart FastAPI to run the runtime-role preflight.
5. Authorize environment-specific role/grant/RLS verification before exposing the
   app. Local tests intentionally refuse live Supabase URLs.

Rollback: migration 0002 refuses automatic downgrade to unprotected access.
Stop the affected application and use a reviewed forward correction; never fix
an outage by disabling RLS or switching runtime credentials to postgres.

## Historical review (not the current implementation status)

ADR-001 and ADR-002 require application checks AND database RLS. The current
migration does not enable RLS or create policies. SQLAlchemy sessions do not
automatically receive a Supabase Auth identity. Phase 1 is not security-complete.

## Options requiring review

1. Direct SQLAlchemy with a restricted runtime login and trusted application
   identity propagation. Separate migration credentials; runtime must not be
   superuser, BYPASSRLS, table owner, or able to assume privileged roles. Policies
   need both USING and WITH CHECK. Transaction-local identity must originate only
   from verified authentication and reset on connection reuse. A plain custom
   setting is NOT authenticated evidence: the runtime SQL principal can change it.
   This option protects against missing owner filters, but not arbitrary SQL
   executed with the runtime credential. Approve that trust boundary explicitly
   before selecting an identity mechanism or writing policies.
2. Database-verifiable identity with direct SQLAlchemy. A narrowly defined,
   reviewed mechanism must verify signed identity and prevent caller-forged owner
   claims, including expiry, issuer, audience, key rotation, and pooling behavior.
   Stronger separation, but significant security implementation and operational
   work. Do not invent a SECURITY DEFINER function or JWT verifier as a shortcut.
3. Supabase Data API using the original user JWT, with API role grants and RLS.
   Uses the platform's verified JWT context, but changes the approved SQLAlchemy
   persistence path and therefore requires an architecture decision amendment.

Recommendation for review: option 1 is smallest if the trusted FastAPI runtime
boundary and its limits are accepted. If database isolation must withstand
arbitrary SQL under the shared backend credential, do not claim option 1 meets
that threat model; evaluate options 2 or 3 instead.

At the time of the initial correction, no role, policy, identity-setting SQL, or migration was added.
Do not expose the application as owner-isolated until this gate is resolved.

## Verification

`tests/test_postgresql_phase1.py` performs a read-only audit using DATABASE_URL:
runtime privilege flags, table-owner bypass, RLS enablement, and policy presence.
Failures are real readiness failures, not skipped successes. This prerequisite
audit alone does not prove policy correctness or audit all role memberships.

Persistence/application-isolation tests require PHASE1_TEST_DATABASE_URL pointing
to a dedicated migrated PostgreSQL test database, plus PHASE1_TEST_RUNTIME_ROLE
matching its current_user. Use the intended runtime-equivalent role, not migration
credentials. Tests insert random-owner records and delete only their own records.
They currently test service isolation, not an unapproved database identity bridge.

After approval, add real-runtime-role tests for owner A/B SELECT/INSERT/UPDATE/
DELETE (including raw SQL without owner predicates), forged owner writes, absent
identity, expired/invalid identity, privileged role membership, and pooled
connection reuse after commit/rollback. Those behavioral RLS tests remain blocked
by the design decision; do not replace them with mocked policies or SET claims.

## Corrections and traceability

- One engine/session factory per application lifespan; one session/transaction per
  request. Commit before response via function-scoped dependency; rollback on
  handler, validation, flush, or commit errors. Repository flush is not commit.
- ADR-001 persistence boundary; AC-001/003: committed creation/configuration.
- ADR-001/002; AC-002: application isolation tests and pending database RLS gate.
- AC-003: PATCH permits omitted fields but rejects explicit null for required data.
- Authentication distinguishes invalid credentials (401) from upstream outage,
  unexpected response, or unavailable configuration (503), without leaking details.

References: [PostgreSQL RLS](https://www.postgresql.org/docs/current/ddl-rowsecurity.html),
[SQLAlchemy sessions](https://docs.sqlalchemy.org/en/20/orm/session_basics.html),
[FastAPI dependency scopes](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/).
