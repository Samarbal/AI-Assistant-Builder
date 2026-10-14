# Phase 2 verification — 2026-10-14

Status: completed after developer approval and final review. Phase 3 not started.
Date uses Asia/Hebron; machine evidence filenames contain UTC timestamps.

## Evidence

- Real two-owner HTTP test, run interactively by the developer and inspected here:
  live report (local evidence; excluded from Git).
- Successful read-only cleanup preflight:
  preflight (local evidence; excluded from Git).
- Authorized cleanup, after the developer confirmed all upload producers stopped:
  apply report (local evidence; excluded from Git).

All three reports have `status: verified`. Earlier unsuccessful preflight evidence
is retained: an initial sandbox connection failure and a stopped preflight. Neither
attempt deleted objects. The latter initially recorded only the exception type;
the helper now records developer-written safe guard messages for diagnosis.

## Actual outcomes

| Check | Result |
| --- | --- |
| Real authenticated owner PDF/DOCX upload and extraction | PASS, HTTP report |
| Both directions of cross-owner list/upload/delete/sign denial and raw RLS isolation | PASS, HTTP report |
| Owner signed download, matching original bytes | PASS, HTTP report |
| Logical removal, repeated DELETE, denial of new links, replacement | PASS, HTTP report |
| Concurrent uploads with four occupied slots | PASS: 201 and 409, overlap 4.3694 seconds, five active slots |
| Runtime role guard, forced RLS/schema baseline and Alembic revision | PASS, cleanup preflight; revision 0003_knowledge_files |
| Exact seven manifest originals physically removed | PASS, Storage API and exact-directory absence checks |
| Repeated completed recovery | PASS: already_complete for all seven |
| Metadata and extracted text retained | PASS, before/after comparison |
| Pending cleanup for the two test assistants | PASS: empty previews after cleanup |
| Earlier retained upload control | PASS: original bytes and checked metadata/text unchanged |

No table/row deletion, migration, grant, policy change, Auth change or bucket sweep
was performed. Test assistants and file/text records remain deliberately. No keys,
tokens, document contents or credentials appear in the evidence reports.

## Tests executed in this change

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cleanup_verification_tool.py tests/test_knowledge_recovery.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -rs -p no:cacheprovider
.\.venv\Scripts\python.exe -m py_compile scripts/verify_phase2_cleanup.py tests/test_cleanup_verification_tool.py
```

- Targeted tests: **28 passed**, one existing warning.
- Full suite: **112 passed, 27 skipped**, three existing warnings.
- Compile: PASS. `git diff --check`: PASS (line-ending notices only).
- Skips: 12 local Phase 1 PostgreSQL cases and 15 local Phase 2 PostgreSQL cases;
  guarded local database configuration is disabled. They are not live-test passes.
- Warnings: Starlette/httpx deprecation and Alembic path_separator notices.
- No lint/type-check command is configured; no such result is claimed.

Failure before/after DB commit, Storage failure/retry, stale claims, active leases
and schema drift are covered by the controlled recovery tests. They use SQLite and
fake Storage; we did not cause real Supabase outages or claim live crash injection,
recovery-operator concurrency stress, or coverage of every file in the bucket.

## Acceptance and boundaries

### Review of the 27 skips

The skip condition is the explicit `PHASE1_LOCAL_PG_TESTS` opt-in, not a failed
assertion or missing application dependency. No test URL was redirected to Supabase.

| Skipped group | Count | Other evidence and remaining limitation |
| --- | --- | --- |
| Phase 1 SQL owner/pooled identity, malformed/missing identity, role/grants, forbidden writes, API commit/rollback, unsafe-role rejection | 12 | Previously completed Phase 1 live verification; Phase 2 live checks also exercised real owner isolation and runtime guards. The local variants were not rerun. |
| Phase 2 raw metadata/text isolation and missing identity | 1 | Prior live runtime database verification and two-owner HTTP/raw RLS report. |
| Last-slot concurrency | 1 | Live overlapping HTTP uploads returned 201/409, exactly five active slots. |
| Immutable identity columns | 4 | Reviewed restricted UPDATE grants and offline migration assertions; live owner_id denial. Separate live probes for each other column were not repeated. |
| CHECK constraints | 5 | Reviewed deployed migration definitions; offline migration and repository validation tests, live slot checks. Every malformed-state mutation was not independently replayed live. |
| Composite FK and unique slot | 1 | Reviewed composite ownership FKs and unique constraints; offline SQL assertions and live slot/concurrency checks. The cross-owner FK mutation variant remains unexecuted locally. |
| Forced RLS and grants | 1 | Prior live schema/runtime verification, repeated cleanup runtime/schema guard. |
| Cross-owner UPDATE and forged text INSERT | 1 | Owner isolation proved live; reviewed RLS WITH CHECK and composite FK. The specific forged INSERT matrix was not repeated live. |
| Reservation rollback | 1 | Prior live runtime test rolled back transient reservations; local variant skipped. |

These skips are non-blocking for this MVP delivery because the critical product
acceptance criteria have recorded live evidence and the schema/security definitions
were reviewed. They remain a coverage limitation, not 27 passing tests or a claim
that all negative SQL permutations were tested on Supabase. Final review only ran
offline/unit tests and inspected existing evidence; it made no live database changes.

Raw JSON evidence is deliberately excluded from Git because it contains live test
identifiers. Public documentation summarizes outcomes; commands containing RUN_UUID
require substitution with a local report. No credentials, tokens, original documents
or raw test records are shipped. Existing local skill/configuration and Docker changes
are outside this Phase 2 release.

- FR-001 / AC-002: authenticated owner isolation for file APIs and RLS.
- FR-003 / AC-004: PDF and DOCX upload/extraction.
- FR-003 / AC-005: owner listing and temporary access to the original.
- FR-003 / AC-006–007: logical removal and remove-then-upload replacement;
  physical recovery is the approved ADR-003 lifecycle support for those workflows.
- Five-file concurrency limit, private Storage and controlled exact-key cleanup
  follow ADR-002/003. Runtime SQL remains restricted as required by ADR-001.

No Phase 2 blocker was observed in these checks. Developer approval for finalization
was received. Recovery requires stopped producers and settled external requests; the CLI
cannot prove that condition automatically. It preserves text/metadata and is not a
full data-erasure system. Before publishing, implement reference-aware cleanup in
place of the temporary frozen-schema gate. Embeddings, indexing, RAG and publishing
remain out of this change. Finalization makes no live Supabase changes.

## Files touched in this change

- Added `backend/scripts/verify_phase2_cleanup.py`: bounded manifest verification.
- Added `backend/tests/test_cleanup_verification_tool.py`: six manifest safety tests.
- Updated `PHASE-2-RECOVERY-RUNBOOK.md` and `PHASE-2-CONTRACTS.md` with current evidence.
- Appended the learning update in `docs/learning/PHASE-2-EXPLAINED.md`.
- Added this summary; raw cleanup preflight/apply JSON reports remain local and ignored by Git.

The application recovery/storage implementation and existing tests were reused;
no application architecture changes or dependencies were added.
