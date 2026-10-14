# Phase 2 operator recovery

Status: implemented; exact-file live cleanup verified on 2026-10-14.

Current evidence: `PHASE-2-VERIFICATION-2026-10-14.md`. Seven recorded test originals
were deleted through Storage API, metadata/text retained, repeat execution checked,
and the earlier control fixture remained unchanged. Earlier results below are historical.

Scope: recorded file operations only. No bucket listing, prefix sweep, database
row deletion, automatic scheduling, migrations, new grants or new dependencies.
FR-003 / AC-006–007 lifecycle reliability; FR-001 / AC-002 owner isolation; ADR-003.

## Credentials and trust boundary

The CLI uses `DATABASE_URL` as `assistant_runtime`, not migration/admin credentials.
Its trusted operator supplies an explicit owner UUID and assistant UUID. Each
transaction sets that identity locally before protected queries; ordinary product
clients cannot invoke this CLI or supply this identity to an HTTP endpoint.
This is the existing trusted FastAPI/operator boundary, not protection against an
attacker with arbitrary SQL execution under the runtime role.

Storage deletion uses the existing server-only `SUPABASE_STORAGE_KEY`. The CLI
verifies that the DB and Storage project identifiers match. Never use credentials
as command-line arguments. Dry-run creates no Storage client and runs a read-only
PostgreSQL transaction. The existing migration password is not needed by this tool.

## Preview first

From `backend`, substitute the actual UUIDs from an assistant response. `owner_id`
is the authenticated account ID, not the assistant ID:

```powershell
.\.venv\Scripts\python.exe scripts/recover_knowledge.py --owner-id "OWNER_UUID" --assistant-id "ASSISTANT_UUID"
```

At most 100 candidate operations are shown, with file ID, operation ID, action and
attempt count. Names, document contents, object paths, signed URLs and keys are not
printed. Empty `operations` means no candidates for this assistant, not a claim
about every account. There is no automatic cross-owner scan.

| Action | Behavior |
| --- | --- |
| `no_action` | Current processing/successful state; no change |
| `mark_expired_failed` | Fence old operation; mark timeout failure; preserve attachment and slot |
| `retain_attached_failed` | Keep failed attachment until owner explicitly removes it |
| `wait_for_quiet_period` | Wait until after lease/removal plus five minutes |
| `delete_recorded_original` | Eligible removed attachment; exact object only |
| `already_complete` | No repeat Storage request |

## Apply one reviewed operation

Before applying, stop **all** API/upload producers, including reload child processes,
and ensure outstanding remote upload requests have settled. Do not run migrations or
publishing during this window. `--writers-stopped` is the operator's acknowledgement;
the CLI cannot prove remote producers have stopped. A DB operation UUID cannot
cancel an upload request already in flight at Storage. Time/leases alone do not
prove remote completion. If uncertain, keep using dry-run and do not delete.

After reviewing a fresh preview, target exactly one file and its current operation:

```powershell
.\.venv\Scripts\python.exe scripts/recover_knowledge.py --owner-id "OWNER_UUID" --assistant-id "ASSISTANT_UUID" --file-id "FILE_UUID" --operation-id "OPERATION_UUID_FROM_PREVIEW" --apply --writers-stopped
```

This is an operational procedure, not blanket authorization to delete arbitrary
files. Review live candidates and obtain authorization for their specific scope.

The tool locks/rechecks the row and requires the exact current operation ID. It
records a new claim and attempt count, and commits that short transaction **before**
contacting Storage. A second operator's old preview is rejected. A newly previewed
claim must wait for its lease and quiet period. Network I/O holds no DB row lock.

The five-minute quiet period begins after the later of `lease_expires_at` and
`removed_at`; this also exceeds the supported signed-link TTL. A claim uses another
five-minute lease. After a failed attempt, re-preview later rather than hot-looping.

Storage returns 200 and an array for the exact-key removal. An empty array is the
already-absent case under the trusted privileged adapter; 403/404/500 or malformed
responses are failures, not proof of deletion. No arbitrary key can be passed to
the CLI. The stored key must exactly match the owner/assistant/file UUID path.

## Failure recovery

- Claim DB transaction fails: no Storage call happens.
- Storage fails or times out: keep `pending`, record `storage_unavailable`, and return
  nonzero. A timeout is ambiguous; a later exact-key retry is safe with writers stopped.
- Storage succeeds but completion DB transaction fails: durable claim remains
  pending; a later retry sees an absent object and can complete bookkeeping.
- Process crashes after claiming: re-preview after lease/quiet period and reconcile.
- Expired attached processing: mark `failed` with `processing_timeout`; do not silently
  remove the owner's attachment or attempt automatic re-extraction. Owner can remove
  then re-upload as specified by AC-007.
- Completion is fenced by the claim UUID. Do not reuse an old operation ID after
  another attempt. Re-preview; if no candidate remains, inspect file metadata rather
  than forcing the operation.

Metadata and extracted text are retained. `cleanup_state=complete` means the original
Storage object was removed/already absent, not that all associated data was erased.

## Published artifacts and future changes

Publishing is not implemented. The cleanup guard checks the frozen Phase 2 public
table/column baseline, absence of public views, forced RLS and `draft` assistant
state. Schema drift or non-draft state blocks cleanup rather than assuming there
are no references. This is a **Phase 2 gate**, not a generic snapshot-reference checker.
Before enabling publishing, replace it with reference-aware retention checks and
test synchronization with publication. Never loosen the gate to bypass a failure.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_recovery.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe scripts/recover_knowledge.py --help
```

Tests cover preview without writes, exact-key deletion, repeat execution, failed
Storage retry, DB failure before/after external deletion, stale claims, a simulated
overlapping operator, ownership/parent checks, invalid keys, future-reference guard,
attached failed-file preservation and active-lease protection. Unit tests use fake
Storage/SQLite and do not establish live PostgreSQL locking or live deletion behavior.
Live mutation was subsequently verified on 2026-10-14. Fault-injection tests remain
controlled unit tests; no outage or privilege change was induced on Supabase.

Executed on 2026-10-12: full suite **106 passed, 27 skipped**, three existing
deprecation warnings. Recovery contributes 22 tests. CLI `--help`, Python compile
checks and documentation whitespace checks passed. A live read-only dry-run for
the retained test assistant returned `operations: []`; no Storage request or DB
update was performed by the CLI. This does not verify the live apply path.

Provider contract: [Supabase remove](https://supabase.com/docs/reference/python/storage-from-remove).

## Recorded live-fixture cleanup verification (2026-10-14)

`scripts/verify_phase2_cleanup.py` verifies the seven artifacts from one successful
`verify_phase2_live.py` report. It rejects unsuccessful, duplicate, mismatched or
unexpected manifests before connecting. This is a verification helper for that
specific fixture shape, not a general cleanup scheduler.

From `backend`, run the read-only preflight first:

```powershell
.\.venv\Scripts\python.exe scripts/verify_phase2_cleanup.py --source ../docs/ai-sdlc/contracts/PHASE-2-LIVE-RUN_UUID.json
```

After the operator confirms all upload producers are stopped and remote uploads
have settled, the authorized apply command is:

```powershell
.\.venv\Scripts\python.exe scripts/verify_phase2_cleanup.py --source ../docs/ai-sdlc/contracts/PHASE-2-LIVE-RUN_UUID.json --apply --writers-stopped
```

The helper uses `MIGRATION_DATABASE_URL` only in a **read-only** transaction to
check the migration revision and resolve owners of the exact recorded assistants.
No administrative writes occur. Recovery, metadata verification and text reads use
`DATABASE_URL` with the restricted runtime role and transaction-local owner identity.
It additionally checks the earlier retained upload fixture as an untouched control.

Before any deletion it verifies all seven candidates, original content hashes,
operation eligibility and the existing schema/RLS guard. After each deletion it
checks the exact object directory is empty, metadata/text remain, and repeating the
completed operation returns `already_complete`. It never empties a bucket, deletes
database rows, changes policies or deletes the control fixture.

Each invocation writes a distinct sanitized `PHASE-2-CLEANUP-*.json` evidence file.
On any failure stop and review that evidence. Do not blindly restart an apply:
partially completed manifests deliberately require individual reconciliation with
`recover_knowledge.py` rather than relaxing the zero-prior-attempt precondition.
