# Phase 1 owner isolation review

Status: pending security design approval

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

No role, policy, identity-setting SQL, or migration was added in this correction.
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
