# Phase 2: Knowledge Upload and Management

Status: Phase 2 completed on 2026-10-14 after developer approval and final review. Phase 3 not started.

Verification update (2026-10-14, Asia/Hebron): full suite **112 passed, 27 skipped,
3 warnings**. Live two-owner HTTP evidence and seven-artifact physical cleanup
evidence are recorded in `PHASE-2-VERIFICATION-2026-10-14.md`. Skipped local
PostgreSQL tests are not claimed as passed; simulated failure tests are distinguished
from actual Supabase success-path checks.

Verification on 2026-10-12 after recovery: full suite **106 passed, 27 skipped**. The skipped cases
are the guarded local PostgreSQL suites, not evidence of success. Separately,
`verify_phase2_database.py` passed on the live Supabase runtime connection:
forced RLS, owner isolation, missing identity, immutable ownership, forbidden
DELETE, five slots, slot uniqueness/range, extraction persistence and rollback.
The subsequent two-owner live report `PHASE-2-LIVE-RUN_UUID.json`
verifies concurrent uploads: overlapping requests returned exactly 201 and 409,
preserving the five-slot invariant. It also verifies owner signed download, logical
removal, replacement and cross-owner denial in both directions. See the cleanup
runbook for the separate physical-recovery verification.

## Approved boundaries

Sources: SPEC-001 FR-001/FR-003, AC-002 through AC-007 and AC-018; ADR-001 through
ADR-005. The upload slice adds authenticated multipart upload, private Storage
adapter, PDF/DOCX extraction, listing and logical removal. Generation, embeddings,
chunking, retrieval and publishing remain excluded. Operator recovery is now
implemented as a separate CLI; live apply now verified on the seven recorded test artifacts.

The original Phase 1 deployment script now targets `0002_assistant_owner_rls`
explicitly instead of `head`, preventing an old Phase 1 command from silently
deploying Phase 2. Neither existing Phase 1 migration was modified.

The approved Storage adapter is server-only and privileged. It bypasses Storage
RLS; application ownership checks are mandatory. It must never replace restricted
SQLAlchemy runtime access. The bucket stays private with no ordinary client access.
Signed download URLs use a configurable 60-second lifetime. A URL already issued
may remain usable after logical removal until expiry; downloaded copies cannot be
recalled. Signed download delivery and operator recovery CLI are implemented;
live recovery verification completed on 2026-10-14; metadata and extracted text remain.

## Owner download contract

`POST /assistants/{assistant_id}/knowledge-files/{file_id}/download-url` requires
the existing Supabase Bearer session. No request body or owner-supplied TTL/object
key is used. The service resolves the active attachment through the restricted
owner-scoped repository, requires `extracted`, signs the stored immutable key, and
rechecks attachment presence before returning the URL.

200: `download_url` plus `expires_in`, with `Cache-Control: no-store` and
`Pragma: no-cache`. `STORAGE_SIGNED_URL_SECONDS` defaults to 60 and remains constrained
to 1–300 seconds by existing deployment settings. The interval starts at signing,
not when the browser opens the URL. 401: unauthenticated. 404: wrong owner/parent,
missing or removed file. 409: not extracted. 503: unavailable database/Storage or
invalid provider response. No new migration, grants or Storage policies are required.

Authorization checks precede signing. No SQL transaction remains open during the
Storage request. A second owner-scoped read rejects removal during signing; once a
URL is delivered it remains usable until expiration under the accepted ADR.
The URL itself contains a temporary access token and must not be logged.

Live adapter verification passed: a 60-second URL downloaded the existing fixture
with matching hash and attachment header, then was rejected after 65 seconds.
The subsequent two-owner live report verifies the endpoint with real authenticated
owners, matching downloaded bytes, wrong-owner denial and denial of a new link after
logical removal. Phase completion remains subject to the recovery report and review.

## Schema and invariants

- `knowledge_files`: immutable owner/assistant/file IDs and object key, display
  filename, PDF/DOCX format, byte size, SHA-256, nullable slot 1..5, ingestion state,
  safe error code, operation UUID, lease expiry, removal timestamp, cleanup state,
  cleanup attempts/error code, creation/update timestamps.
- `knowledge_file_text`: one immutable extracted text row per file, ownership
  relationship and extraction version. No vectors or chunks.
- Composite FKs require file owner to equal assistant owner and text ownership to
  equal file ownership. No cascading deletion.
- `(assistant_id, slot_number)` is unique. Attached records require a slot; removed
  records require a null slot. All attached states, including failed, count toward
  five. The schema uses decimal MB: 10 MB = 10,000,000 bytes, consistent with the
  proposed contract. Defensive extraction guards are documented in the runbook;
  they are implementation resource limits, not additional supported document types.
- Reservation locks the owner-scoped assistant before choosing a slot. The unique
  constraint remains the final backstop. Use PostgreSQL READ COMMITTED (the default).
  A serialization/lock error must roll back the operation; no hidden retry here.
- Object paths are generated from server UUIDs, never filenames. Every new upload
  receives a fresh path. Repository transactions do not perform Storage I/O.

## Lifecycle and transactions

`accepted -> processing -> extracted`; accepted/processing may transition to failed.
Start/finalize require the matching operation UUID, an unexpired lease, and an
attached file. Invalid transitions raise `KnowledgeStateConflict`. Caller must
roll back on exceptions. Text insertion and extracted-state update commit together.

Logical removal locks assistant then file, clears the slot, records removal, marks
cleanup pending, and rotates the operation UUID to fence late work. It is idempotent
and preserves text/object identity. It performs no physical deletion. Removed rows
are excluded from ordinary lists/gets but remain available to scoped maintenance.
Expired operations are not automatically reclaimed; the operator recovery CLI handles
recorded operations as described in `PHASE-2-RECOVERY-RUNBOOK.md`.

Caller sets verified transaction-local `app.owner_id` before any repository query.
Each repository accepts owner and assistant IDs and never commits. Use short
transactions around external work in subsequent steps. No authentication redesign.

## RLS and permissions

Both new tables ENABLE and FORCE RLS. SELECT/INSERT owner predicates target
`assistant_runtime`; knowledge metadata UPDATE has USING and WITH CHECK predicates.
Missing identity hides rows and denies inserts; malformed UUID identity fails.
Knowledge metadata UPDATE is limited to lifecycle, slot, lease and cleanup fields.
Owner/assistant/file IDs, object key, hash and original metadata are immutable.
Text has SELECT/INSERT only. Neither table grants runtime DELETE/TRUNCATE or schema
ownership. PUBLIC, anon, authenticated and service_role table/column grants are
revoked on the new tables only. Supabase Auth/Storage schemas are untouched.

The privileged Storage key does not authorize relational Data API access to these
tables. The existing trusted-app session-variable limitation remains unchanged.
Database constraints enforce valid states; allowed transition ordering and lease
checks are repository responsibilities, not protection against arbitrary runtime SQL.

## Recovery and snapshot compatibility

Update: `scripts/recover_knowledge.py` now implements the operator workflow. Its
default is a read-only, owner/assistant-scoped preview; apply targets a single
reviewed file and operation UUID and requires stopped/settled upload producers.
Existing restricted runtime UPDATE grants suffice. No DB DELETE, new role, admin
runtime, migration or scheduling is introduced. See
[the recovery runbook](PHASE-2-RECOVERY-RUNBOOK.md) for current behavior; the following
paragraph describes the original Step 1 boundary.

Operation ID, lease, timestamps, exact key and cleanup fields support later
operator-invoked reconciliation. Pending cleanup is a request, not permission to
delete: check retained snapshot references first. No snapshot tables, cleanup CLI,
Storage deletes or privileged credentials are added in Step 1. Before publication
is enabled, reference-aware cleanup must be implemented. No automatic hard deletes
or security-weakening downgrade exist in this migration.

## Verification (from backend)

Local tests, no developer credentials or network database access:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -r s -p no:cacheprovider
```

Render just the additive migration without connecting to any database:

```powershell
$env:MIGRATION_DATABASE_URL='postgresql+psycopg://offline:placeholder@localhost/offline'
.\.venv\Scripts\python.exe -m alembic upgrade 0002_assistant_owner_rls:0003_knowledge_files --sql
Remove-Item Env:MIGRATION_DATABASE_URL
```

Real PostgreSQL tests require an explicitly provisioned disposable LOCAL database
`assistant_builder_phase1_test`, migration login, restricted `assistant_runtime`
login, and stand-in `anon`/`authenticated` roles (reuse Phase 1 local setup).
Runtime must not inherit public-schema CREATE; an administrator owns tables.
Populate the two local-only connection variables in your terminal without logging
credentials. URLs must target localhost/127.0.0.1/::1 and have no query overrides.
Do not use Supabase URLs or developer `.env` for these tests.

```powershell
# Set PHASE1_LOCAL_MIGRATION_URL and PHASE1_LOCAL_RUNTIME_URL locally first.
$env:PHASE1_LOCAL_PG_TESTS='1'
.\.venv\Scripts\python.exe -m pytest tests/test_postgresql_phase1.py tests/test_postgresql_phase2.py -q -r s -p no:cacheprovider
Remove-Item Env:PHASE1_LOCAL_PG_TESTS
```

The fixture applies Alembic head ONLY to that guarded local test database. Cleanup
deletes only generated test-owner rows there. The subsequent explicit user request
authorized live deployment of 0003 only, completed on 2026-10-12. Do not redirect
these local test URLs at Supabase; use the separate bounded live verification script.
SQLite tests verify repository behavior, not PostgreSQL RLS or concurrency.
