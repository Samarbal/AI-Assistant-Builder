
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

Knowledge processing, semantic RAG, embeddings, playground responses, publishing, the public widget, and visitor chat are planned for later phases and are not implemented yet.

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

Apply the migration and start the development server:

```powershell
uv run alembic upgrade head
uv run uvicorn assistant_builder.main:app --reload
```

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

## Tests and checks

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
