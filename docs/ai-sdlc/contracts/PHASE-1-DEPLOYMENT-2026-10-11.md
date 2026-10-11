# Phase 1 deployment attempt — 2026-10-11

Status: Phase 1 verified and complete within its approved backend scope.

## Final acceptance — 2026-10-11

The developer ran `scripts/signin_phase1.py` locally with two dedicated Supabase
Auth accounts. Its saved PHASE-1-LIVE-RESULTS.json matches the supplied console
output: **9 live verification groups passed, none skipped**, revision
`0002_assistant_owner_rls`, status `verified`. Three current-run API fixtures were
cleaned up; no retained assistant IDs remain. Runtime DELETE remains forbidden.
This closes the previous authenticated-owner acceptance blocker. Earlier pending
statuses below are historical and are superseded by this section.

Coverage: FR-001 / AC-001 and AC-002 (multiple independent assistants and owner
isolation), the Phase 1 scalar configuration portion of FR-002 / AC-003, and the
Phase 1 API portion of AC-018 (no model/code inputs). Knowledge associations and
other later workflows remain deferred; this does not claim completion of all MVP
acceptance criteria or user-interface usability testing.

The local suite reports 46 passed and 12 skipped dedicated-local-PostgreSQL cases;
live Supabase checks above provide separate database evidence. No architecture
change or Phase 2 implementation was made. Phase 2 may be planned after review of
the learning report. The session-variable trust boundary remains documented:
arbitrary SQL under the runtime role can change its identity setting.

## Secure two-owner verification

Run in your own interactive terminal from `backend`:

```powershell
.\.venv\Scripts\python.exe scripts/signin_phase1.py
```

Enter each dedicated test user's email at the visible prompt and password at the
hidden prompt (no characters or stars appear while typing). Do not
put passwords in command arguments, chat, or source files. The helper uses existing
`SUPABASE_URL` and `SUPABASE_ANON_KEY` configuration, HTTPS password sign-in, and
the existing Supabase user verifier. Tokens stay in process memory; no password,
access token, refresh token, or response body is printed or saved to `.env`.
Two distinct authenticated users are required before starting live verification.

The helper runs the existing live checks without authentication overrides. Only
after they pass, an administrative cleanup transaction deletes the exact assistant
IDs created in that run, checking their owner UUID, unique run marker, and draft
state first. Unexpected triggers, referencing foreign keys, rules, changed rows,
or deletion counts stop cleanup. No broad owner-based deletion, historical-record
cleanup, runtime DELETE grant, or RLS changes are allowed. Failed verification
leaves fixtures listed in the sanitized report for review rather than deleting
possible evidence. Interrupted runs may require manual review of retained fixtures.

Local helper safety tests: **41 passed, 12 skipped**, with two dependency
deprecation warnings. The interactive live test has not yet run with the new
accounts; account creation alone does not supply login credentials. Finalization,
commit and push remain conditional on its successful result.

## Finalization verification rerun — 2026-10-11

- Local command: `python -m pytest -q -r s -p no:cacheprovider`, with
  `PHASE1_LOCAL_PG_TESTS=0`: **36 passed, 12 skipped, 2 deprecation warnings**.
  The skipped cases require a dedicated local PostgreSQL database; they were not
  redirected to the live project.
- Live command: `python scripts/verify_phase1_live.py`: **7 verification groups
  passed** using the deployed restricted runtime login. Alembic revision remains
  `0002_assistant_owner_rls`; the approved trigger baseline is unchanged, RLS is
  enabled and forced, and inspected Data API table/column grants are absent.
- The first sandboxed live connection failed with `OperationalError`; the
  network-authorized rerun above succeeded. No migration or privilege change was
  required. All transient database fixtures were rolled back.
- Real authenticated-owner endpoint verification remains **SKIPPED/BLOCKED**:
  `PHASE1_OWNER_A_TOKEN` and `PHASE1_OWNER_B_TOKEN` are unavailable locally.
  Synthetic owner UUID isolation and mocked-auth endpoint tests do not replace
  this end-to-end check. DELETE remains intentionally excluded from Phase 1.
- Git review found no known local credential matches or token/private-key pattern
  candidates in 66 changed/untracked text files. `.env` is ignored and untracked;
  `git diff --check` passed. This targeted scan is not a guarantee of secret absence.
- Phase 1 remains pending acceptance, and Phase 2 has not started. No finalization
  commit or push was made on `main`: the required authenticated-owner check must
  pass first. Keep unrelated skill/tooling changes out of the implementation commit.

## Subsequent authorized deployment

The exact reviewed function definition, owner, SECURITY DEFINER, search_path and
trigger name/events/status were rechecked. No general public-function exemption
was added. The original auto-RLS objects were left unchanged.

assistant_runtime was provisioned and revisions 0001_create_assistants and
0002_assistant_owner_rls applied in a single transaction. DATABASE_URL was saved
locally using the restricted login; migration credentials remain separate. No
credentials were logged/committed and no push was performed.

Seven live verification groups passed; see PHASE-1-LIVE-RESULTS.json. These include
actual runtime login, grants, forced RLS, raw SQL owner isolation, missing/invalid
identity, rejected writes, rollback and reuse. All synthetic data was rolled back.
Two real authenticated-owner API tests remain unavailable because owner access
tokens were not supplied. No accounts were created or authentication bypassed.

Local checks: 28 passing tests in the complete suite, 12 local PostgreSQL cases
skipped; 8 additional baseline tests passed separately. Phase 1 acceptance is not
declared complete until authenticated HTTP persistence/configuration/isolation
is verified. The following text records the earlier, resolved preflight stop.

## Historical stopped attempt

The authorized target connection succeeded as postgres on database postgres.
Public application tables, alembic_version, and assistant_runtime were absent.
The deployment preflight additionally found public.rls_auto_enable, a non-extension
SECURITY DEFINER event-trigger function owned by postgres, with search_path fixed
to pg_catalog. Its enabled event trigger ensure_rls runs after CREATE TABLE,
CREATE TABLE AS and SELECT INTO, enabling RLS on new public tables.

The inspected definition does not disable RLS or grant public access. Its presence
is not by itself evidence of a vulnerability. However, it is an existing schema
object outside the reviewed deployment baseline. The user's stop-on-unexpected-
objects condition was honored; no whitelist or bypass was added automatically.

No runtime role/password was provisioned, no migration executed, no .env value
changed, and no application data inserted or deleted. Live RLS tests were not run.
The local deployment script and connection-injection support in Alembic were
prepared but the script stopped before the mutation transaction.

Review needed: approve retaining this specific existing auto-RLS trigger and
recognizing its inspected definition as part of the baseline. If approved, compare
the definition and trigger configuration again before accepting it; continue to
reject unrelated or changed functions. No change to the existing trigger is needed
based on the inspected behavior. Phase 1 remains incomplete pending deployment
and real runtime-role verification.
