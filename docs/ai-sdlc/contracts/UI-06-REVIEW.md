# UI-06: Frontend review and verification

Date: 2026-10-20
Status: Local review complete; live frontend verification and human review pending.

## Findings and scope

- Fixed the empty assistant parent route: `/assistants/:id` now redirects to its configuration screen.
- Fixed corrupted punctuation in assistant loading messages.
- Fixed keyboard focus after removal confirmation: Cancel restores the initiating Remove button; successful removal focuses the Attached files heading.
- Reviewed shared shell/navigation, protected routes, form states, narrow layouts, long filenames, loading/error/empty states, and knowledge contracts. No backend contract change was needed.
- Bundle splitting, additional visual polish, and broader assistive-technology/cross-browser testing are enhancements, not confirmed functional defects. This review is not a full accessibility certification.

## Knowledge contract review

All paths below are relative to `/assistants/{assistant_id}/knowledge-files`.

| Operation | Contract | Frontend behavior |
| --- | --- | --- |
| GET collection | 200 metadata array | Authenticated list and refresh |
| POST collection | Multipart `file`; 201 metadata | PDF/DOCX; 1–10,000,000 bytes; five attachments; backend authoritative |
| DELETE `/{file_id}` | 204, no response body | Confirmation, draft detachment, list reconciliation |
| POST `/{file_id}/download-url` | 200 `download_url`, `expires_in` | Transient HTTPS link, local expiry, no bearer token forwarded |

Failed attachments count toward the limit. Processing states are not presented as RAG readiness. Mutations are never automatically retried; uncertain results trigger list reconciliation. Session/account changes abort and discard owner-specific state. Controlled responses do not prove deployed RLS or Storage policies.

## Safe live smoke-test procedure — not executed

Explicit approval is required before these steps create or remove live records. Do not run migration, bucket setup, recovery apply, or administrative cleanup as part of this test.

1. Use existing dedicated test accounts and an approved disposable assistant. If creating one through the UI is approved, retain its metadata afterward: no assistant deletion endpoint exists. Stop if the chosen assistant contains unrelated files.
2. Prepare a small text-based PDF, DOCX, and replacement PDF with synthetic business text, each under 100 KB. Never use customer documents.
3. Use existing local configuration for the same Supabase project. Never copy privileged credentials into frontend configuration or record tokens/passwords.
4. Start the backend from `backend/`:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn assistant_builder.main:app --host 127.0.0.1 --port 8000
   ```

5. In a second terminal, from `frontend/`, run `npm.cmd run dev`. Open `http://127.0.0.1:5173/login` and sign in locally. Use the real dev server, not the mocked browser-test server.
6. Open the disposable assistant's Knowledge screen. Verify GET 200 and the expected initial list. Upload PDF and DOCX separately: POST 201 with `extracted`, then GET 200. Reload and confirm both remain listed.
7. Download each file: POST download-url 200, then signed download 200 and original bytes. Verify the displayed link expires and a new authenticated request creates a new link. Never capture signed URLs in shared evidence.
8. Remove only a current-run attachment: DELETE 204 and absence after refresh/reload. Upload the replacement and confirm 201. Previously issued links may remain usable until expiry; removal is logical, not immediate physical erasure.
9. Log out and confirm protected content is unavailable. Sign in as the other dedicated owner and navigate to the first assistant's knowledge path; verify denied access and no first-owner file data. Do not modify unrelated records.
10. Return to the original owner and logically remove only this run's remaining attachments; confirm the initial list is restored. Record exact test IDs locally if needed. Physical Storage cleanup is separate operator work requiring its own approval; do not claim bytes were erased.
11. Record sanitized PASS/FAIL, response statuses, and time. Do not share HAR files, Authorization headers, credentials, or signed URLs. Stop on cross-owner disclosure, unexpected records, or security failures. Reconcile the list before retrying an uncertain upload.

## Local verification results

- `npm.cmd test -- --maxWorkers=1`: 51 passed, four files, no skips. The preceding concurrent run failed to start workers; the successful serial rerun exited 0.
- `npm.cmd run test:browser`: 20 Chromium tests passed, no skips, exit 0. Includes three UI-06 regressions and existing shell/auth/assistant/knowledge scenarios with controlled HTTP responses.
- `npm.cmd run lint`: passed. `npm.cmd run build`: passed, including TypeScript. Existing 543.79-kB minified JS chunk warning remains (158.54 kB gzip); no dependency changes.
- Backend upload/download contract tests: 32 passed; existing Starlette/httpx deprecation warning. These local tests do not verify deployed PostgreSQL or Storage.
- Reviewed the 320px long-filename screenshot and keyboard focus behavior. Existing browser checks cover shell widths 320/390/768/1440 and authentication/knowledge mobile and desktop layouts.
- No live frontend-to-backend smoke test performed. No live mutations, deployment, commit, or push.

## Traceability and gate decision

UI-02–05 support FR-001–003, AC-001–007/018 and NFR-001/002. This review adds navigation and keyboard regression coverage; it does not revalidate live owner isolation. Phase 2 backend remains completed. Phase 3 remains planned.

Recommendation: **NO-GO for closing the UI sprint and starting Phase 3 until the scoped live smoke test and human review pass.** Ready for that approved smoke test; no known remaining local functional blocker from this review.
