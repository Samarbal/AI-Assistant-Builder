# Phase 2 upload slice — 2026-10-12

Status: upload verified by the user's live run; signed-download implementation added.
Phase 2 is not complete. No embeddings, retrieval or publishing were added.

## Verified deployment

`deploy_phase2_schema.py` checked the configured Supabase project, actual runtime
role, exact approved auto-RLS function/trigger, revision 0002, absence of conflicting
tables and existing assistant data. It applied only `0003_knowledge_files` in one
transaction. Both knowledge tables have ENABLE/FORCE RLS and restricted grants.
The assistants table and existing Phase 1 migrations were preserved.

Live `verify_phase2_database.py`: PASS for actual assistant_runtime login, forced
RLS, no DELETE/owner_id UPDATE, five-file repository limit, slot range/uniqueness,
metadata/text owner isolation, missing identity, extracted text persistence and
rollback of all generated fixtures. This checks trusted owner UUID propagation,
not real Supabase Auth sessions. No existing records were changed.

Automated suite after recovery addition: 106 passed, 27 skipped; three existing deprecation warnings.
The skipped cases require the explicitly guarded local test database. They were
not run against Supabase. Live concurrent-upload verification is still pending.

## Implemented request flow

Supabase Bearer authentication → owner-scoped short transaction → reserve slot
and immutable object key → bounded text-extraction subprocess → server-only private
Storage upload without upsert → owner-scoped short transaction committing text and
`extracted` state → 201 metadata response.

`POST /assistants/{assistant_id}/knowledge-files`: multipart field `file` only.
`GET /assistants/{assistant_id}/knowledge-files`: current draft attachments.
`DELETE /assistants/{assistant_id}/knowledge-files/{file_id}`: logical removal,
204, slot release, pending cleanup; original object and extracted text are retained.
Neither object paths nor credentials nor extracted text appear in upload responses.

`POST /assistants/{assistant_id}/knowledge-files/{file_id}/download-url`: returns
`download_url` and server-configured `expires_in` (default 60 seconds) for an
owner's current extracted attachment. The JSON response is marked `no-store`.
The URL grants temporary access to anyone holding it; do not log or share it.
See README's download steps and the Phase 2 learning report for verification limits.

Authentication executes before multipart parsing. Swagger uses HTTP Bearer
Authorize; validation still calls the existing Supabase Auth user endpoint.
`owner_id` is never accepted from the caller. Repository checks and transaction-local
owner identity precede all protected queries. Privileged Storage credentials are
separate from the restricted SQLAlchemy connection.

## Configure and test (PowerShell, from backend)

1. In Supabase project Settings → API Keys, obtain a server-only secret key (or
   legacy service_role). Set `SUPABASE_STORAGE_KEY` in the ignored `backend/.env`.
   Keep the existing SUPABASE_URL, SUPABASE_ANON_KEY and restricted DATABASE_URL.
   Never paste a Storage key into Swagger or a user access-token field.
2. Run the bucket setup. It refuses unexpected Storage policies or incompatible
   existing bucket settings; it does not change shared policies:

   ```powershell
   .\.venv\Scripts\python.exe scripts/setup_phase2_storage.py
   ```

3. Run the real upload check; enter an existing test owner's credentials locally:

   ```powershell
   .\.venv\Scripts\python.exe scripts/verify_phase2_upload.py
   ```

   Passwords are hidden, tokens stay in memory. This creates and retains one named
   test assistant and DOCX for inspection. A sanitized report records their IDs and
   actual results. It verifies committed text/metadata, private original bytes,
   denied public/direct-owner Storage access and the owner list endpoint.

4. Start the API:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn assistant_builder.main:app --reload
   ```

5. In a second backend terminal, obtain your user token without printing it:

   ```powershell
   .\.venv\Scripts\python.exe scripts/swagger_login.py
   ```

   This Windows helper places the short-lived user token on your clipboard.
   Open http://127.0.0.1:8000/docs → Authorize → paste token without `Bearer`.
   Clear the clipboard after pasting: `Set-Clipboard -Value ""`.
6. Use GET /assistants to choose your assistant, or POST /assistants with:

   ```json
   {"name":"Support","role":"Customer support","colors":{},
    "response_style":"Concise","tone":"Friendly","fallback_message":"I cannot find that answer."}
   ```

7. Open POST /assistants/{assistant_id}/knowledge-files → Try it out → enter ID,
   choose a text-based PDF or DOCX (at most 10,000,000 bytes) → Execute.
   Expect 201 and `processing_state: extracted`. GET lists the attachment.

## Failure and resource limits

- Failed parsing returns sanitized 422 and records failed/pending cleanup. Failed
  attachments count toward five until logically removed.
- Storage failure returns sanitized 503 and records cleanup pending. An uncertain
  final database commit leaves a durable reservation for operator reconciliation;
  never blindly retry or delete the associated object.
- Authentication failure is 401; another owner's parent/file is 404; five files is
  409; an oversized upload is 413. Unknown transaction failures return 503.
- PDF and DOCX are validated by parsers, not MIME labels. Encrypted, malformed,
  unsupported and text-empty/scanned-only documents fail. No OCR is performed.
- Parsing runs in a separate process with a 30-second deadline and without
  database/Storage secrets in its environment. Guards: 200 PDF pages, 5 MB decoded
  page content, 2 million output characters; DOCX 2,000 ZIP entries/50 MB expanded.
  These are defensive MVP implementation ceilings. Process separation is not a
  full OS sandbox or a hard memory cap; pathological decompression remains a risk.
- Storage setup creates a private 10 MB PDF/DOCX bucket only after verifying that
  no existing object policies grant clients access. Later Storage-policy changes
  require rechecking this boundary.

## Remaining Phase 2 work

Live bucket setup and authenticated upload passed in the user's recorded run.
The signed-download endpoint is implemented; its new authenticated live check is
included in `verify_phase2_upload.py` for the next interactive run. Operator-invoked
recorded-operation recovery is implemented in `recover_knowledge.py` (see the
recovery runbook); live physical cleanup/retry verification, live concurrency
and two-owner upload endpoint testing remain. Future snapshot references must block physical cleanup.
No automatic cleanup, scheduled jobs or publication references were introduced.

Traceability: FR-003/AC-004 upload and extraction; AC-005 listing; AC-006/007 logical
removal and remove-then-upload. Owner boundaries support FR-001/AC-002; configuration
stays server-side under AC-018. Tests for these slices do not claim full Phase 2
acceptance until the remaining access/recovery/live checks are completed.
