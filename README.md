
# AI Assistant Builder

AI Assistant Builder is a platform for business owners who want to create a specialized customer-service assistant, provide it with their business knowledge, test it, publish it, and embed it on their website.

## Product workflow

1. Create one or more assistants.
2. Configure each assistant's name, role, appearance, response style, tone, and fallback message.
3. Add business knowledge from PDF and DOCX files.
4. Test the current draft in the chat playground.
5. Publish the assistant when it is ready.
6. Copy the generated JavaScript snippet into a website to show the chat widget.
7. Review basic conversations and message timestamps from the owner dashboard.

The assistant must answer from the business knowledge. When sufficient relevant knowledge is unavailable, it returns the configured fallback instead of inventing a business-specific answer.

## Current implementation status

Phase 1 is implemented and covers the owner-scoped assistant and configuration foundation:

- FastAPI application foundation.
- Supabase Auth owner context boundary.
- SQLAlchemy and PostgreSQL database foundation.
- Alembic migration foundation.
- Owner-scoped assistant creation, listing, and updating.
- Draft assistant configuration state.
- Contract tests for authentication, ownership isolation, validation, and assistant workflows.

Phase 2 is completed: PDF/DOCX upload, text extraction, private file storage, attachment listing, logical removal/replacement, temporary owner downloads, and operator recovery. Final checks: 112 passed, 27 local PostgreSQL tests skipped; critical workflows were separately verified on Supabase. See the [completion review](docs/ai-sdlc/contracts/PHASE-2-VERIFICATION-2026-10-14.md) for evidence and limitations. Semantic RAG, embeddings, playground responses, publishing, the public widget, and visitor chat are not implemented yet.

## Architecture

```text
FastAPI routes
      |
Owner authentication and authorization
      |
Application services
      |
Owner-scoped repositories
      |
SQLAlchemy sessions
      |
Supabase PostgreSQL
```

Clients never provide or override `owner_id`; it is derived from the authenticated Supabase user. Accepted architecture decisions are documented in [`docs/ai-sdlc/adr/`](docs/ai-sdlc/adr/).

## Local development

Requirements: Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and a PostgreSQL-compatible Supabase project for integration testing.

From the repository root:

```powershell
cd backend
uv sync
```

Create `backend/.env` with local deployment settings. Keep this file private; it is ignored by Git.

```env
DATABASE_URL=postgresql+psycopg://...
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
ENVIRONMENT=development
```

For an already configured database, start the development server:

```powershell
uv run uvicorn assistant_builder.main:app --reload
```

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

Database migrations are a separate deployment step using `MIGRATION_DATABASE_URL`;
they are not required each time you start the server. For Storage setup and live
verification, see the [Phase 2 upload runbook](docs/ai-sdlc/contracts/PHASE-2-UPLOAD-RUNBOOK.md).

## Quick reference: upload a document through Swagger

These Windows PowerShell steps assume the existing virtual environment, database
migrations, private Storage bucket, and `backend/.env` are already configured.
Run the commands from `backend/`. If your terminal is at the repository root,
run `cd backend` first.

### 1. Start the API

```powershell
.\.venv\Scripts\python.exe -m uvicorn assistant_builder.main:app --reload
```

Leave this terminal running and open **http://127.0.0.1:8000/docs**.
The root URL `/` and `/favicon.ico` can return `404 Not Found`: no homepage or
favicon is implemented. This does not indicate that the API failed to start.
Use `Ctrl+C` in the server terminal when you want to stop it.

### 2. Sign in and authorize Swagger

Open a second PowerShell terminal in `backend/`:

```powershell
.\.venv\Scripts\python.exe scripts/swagger_login.py
```

Enter your existing test owner's email and password. Password input is hidden;
type or paste it and press Enter. The helper copies the user access token to your
Windows clipboard without printing it.

In Swagger, click **Authorize**, paste the token **without** the word `Bearer`,
then click **Authorize → Close**. Use the user token, never the Storage secret key.
After pasting, clear the clipboard:

```powershell
Set-Clipboard -Value ""
```

If the session expires and requests return `401`, run the login helper again and
replace the token in Swagger.

### 3. Select an assistant and upload

1. Expand **GET /assistants → Try it out → Execute**.
2. Copy the `id` of an assistant belonging to your signed-in owner. If the list is
   empty, create one with **POST /assistants** first.
3. Expand **POST /assistants/{assistant_id}/knowledge-files → Try it out**.
4. Paste the assistant ID, choose one text-based PDF or DOCX, then click **Execute**.
5. Expect **201 Created** and `"processing_state": "extracted"`.
6. Use **GET /assistants/{assistant_id}/knowledge-files** to list its attachments.

Each assistant allows five current draft attachments, including failed uploads;
each file can contain at most **10,000,000 bytes (10 MB)**. Scanned-only PDFs require
OCR, which is not supported. To release a slot, use
**DELETE /assistants/{assistant_id}/knowledge-files/{file_id}**. This removes the
draft attachment logically; it does not immediately erase the stored artifact.

### 4. Download an uploaded file

1. Copy the file's `id` from the knowledge-file list (different from the assistant ID).
2. Open **POST /assistants/{assistant_id}/knowledge-files/{file_id}/download-url**.
3. Click **Try it out**, enter both IDs, and **Execute** while authorized as the owner.
4. A **200** response contains `download_url` and `expires_in` (default **60 seconds**).
5. Open `download_url` immediately in a new browser tab to download the original file.
   If it expires, request a new URL using the same endpoint.

Only current, successfully extracted attachments can receive a new download link.
A different owner, wrong parent ID, missing file or removed attachment returns 404;
an unfinished/failed attachment returns 409. The lifetime is configured server-side
with `STORAGE_SIGNED_URL_SECONDS`, not supplied by the caller.

The URL is a temporary bearer credential: anyone holding it can download until it
expires. Do not share it or include it in screenshots. Logical removal prevents new
links but does not revoke already-issued links or downloaded copies.

For the Arabic architecture walkthrough and tests, see
[Phase 2 learning report](docs/learning/PHASE-2-EXPLAINED.md).

## Tests and checks

For interrupted uploads and removed-file cleanup, use the developer-only
[recovery runbook](docs/ai-sdlc/contracts/PHASE-2-RECOVERY-RUNBOOK.md).
Preview is read-only and does not contact Storage:

```powershell
# From backend; replace both placeholders with actual UUIDs.
.\.venv\Scripts\python.exe scripts/recover_knowledge.py --owner-id "OWNER_UUID" --assistant-id "ASSISTANT_UUID"
```

Actual cleanup requires a reviewed file/operation and a maintenance window with
upload producers stopped. Follow the runbook; do not add `--apply` to a routine check.

Run these commands from `backend/`:

```powershell
uv run pytest -q
uv run python -m compileall -q src tests
uv run alembic heads
```

## Repository documentation

- [`AGENTS.md`](AGENTS.md): project development rules.
- [`intent/ai-assistant-builder.md`](intent/ai-assistant-builder.md): approved product intent.
- [`docs/ai-sdlc/specs/SPEC-001.md`](docs/ai-sdlc/specs/SPEC-001.md): MVP specification.
- [`docs/ai-sdlc/contracts/`](docs/ai-sdlc/contracts/): Phase 0 contracts and fixtures.
- [`docs/ai-sdlc/plans/`](docs/ai-sdlc/plans/): implementation planning.
- [`docs/ai-sdlc/adr/`](docs/ai-sdlc/adr/): accepted architecture decisions.
