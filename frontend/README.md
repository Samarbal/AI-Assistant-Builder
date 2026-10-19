# Owner frontend — UI-04

React + TypeScript + Vite with Supabase email/password authentication. Owner routes
are protected; assistant API integration is implemented. Knowledge integration remains
deferred. Run FastAPI for assistant workflows. The public marketing page is not implemented.

## Run locally

Use Node.js 22.12+ (verified with 22.22.0) and npm. From the repository root:

```powershell
cd frontend
npm ci
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
npm run dev
```

Open `http://127.0.0.1:5173`. If the port is occupied, Vite prints its chosen port.
Stop with Ctrl+C. This is the frontend; FastAPI Swagger remains a separate backend UI.

Before testing real Auth, set `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`
in `frontend/.env.local` to your existing project's public URL and publishable key.
Legacy `anon` keys are accepted; secret/service_role keys are rejected. Never copy
`backend/.env`. Restart Vite after changes. Missing configuration displays a safe
setup message; the development preview remains available without configuration.

```powershell
npm run build
npm run preview -- --port 4173 --strictPort
```

Open `http://127.0.0.1:4173` for the production build preview. Vite preview is a local
verification tool, not a production hosting decision. Future static hosting must
serve `index.html` for browser routes so refreshed deep links work.

## Checks

```powershell
npm run typecheck
npm run lint
npm test
npm run build
npx playwright install chromium
npm run test:browser
```

The browser suite starts/stops its own loopback Vite server on port 4173; stop a
manual preview on that port first. Browser installation is needed only on first
setup or after a Playwright update. Generated screenshots/reports are ignored.

## Structure and routes

- `src/main.tsx`: React and BrowserRouter entry point, local fonts and styles.
- `src/app/`: nested routes, shared desktop/sidebar/mobile shell, route focus.
- `src/auth/`: public config, Supabase adapter, session store/provider, owner guard,
  responsive auth forms and safe error mapping.
- `src/pages/`: overview and explicitly labeled feature placeholders; no data requests.
- `src/assistants/`: authenticated HTTP client, list and create/edit forms.
- `src/components/`: Button, ButtonLink, TextField, Badge, Card, Alert, EmptyState,
  LoadingState, and local design icons.
- `src/styles/`: Figma-derived tokens and global keyboard/layout defaults.
- `src/assets/`: local Figma SVGs and provenance notes.
- `tests/`: component contracts and Chromium responsive/navigation checks.

Routes: `/` reserved for future marketing (minimal placeholder), `/login`, `/register`;
`/assistants` is the authenticated dashboard. `/assistants/new` and
`/assistants/:id/configuration` are connected forms; `knowledge` remains a protected placeholder.
`/dev/dashboard` is an unauthenticated UI-only preview in development builds only;
it does not grant access to owner routes and is absent in production builds.

Authentication and assistant workflows are functional; knowledge integration,
Playground, publishing and conversations remain deferred.

## Manual Auth review

1. Open `/login`; enter an existing test owner's credentials locally.
2. Confirm navigation to `/assistants`, then reload to verify session restoration.
3. Open a protected assistant configuration route; it loads that owner's draft.
4. Log out. Revisit `/assistants` or use browser Back: login must be required.
5. Log in with a second test account. No previous component state should remain.
6. To test registration, use `/register` with a dedicated test email. If Supabase
   returns no session, the UI shows a confirmation-next-step message instead of
   pretending to log in. Complete any existing confirmation process and log in.
   Registration may send email/create a user; do this only for intended test accounts.
7. Test invalid credentials and network failure; raw provider details are not shown.

No live Auth settings were changed. Confirmation redirect configuration is owned by
the existing Supabase project; UI-03 does not add callback, password reset or OAuth
flows. Returning manually to `/login` after confirmation is supported.

## Security and scope

Only the Supabase SDK persists sessions, using sessionStorage and a project-specific
key. Closing a tab normally removes that tab's storage; browser restoration/duplicated
tabs and SDK auth events mean this is not a security guarantee or global logout.
Storage remains accessible to JavaScript: prevent XSS and never log tokens. The
small signed-out marker contains no credentials and prevents restoring a failed
logout on reload. Logout uses `scope: local`; failed server revocation is reported.
Already-issued access JWTs may remain valid until expiry.

All `VITE_*` values are browser-visible. Route guards are UX only; FastAPI and RLS
remain authoritative. The assistant API client obtains the current SDK session's access
token, sends it as `Authorization: Bearer` to FastAPI, and discards pending results on
owner/session change. Owner subtree remounts clear component state on logout/account
switch; pending requests are aborted. There is no persistent assistant cache.

Automated browser checks use the real SDK against mocked Auth HTTP responses with
non-secret `.example.test` settings supplied only to the test server. They are not
live Supabase verification. Playwright's mode-specific Vite cache avoids collisions
with a concurrently running development server. The development server must not be
used to serve production traffic.

Dependencies are pinned in `package.json` and `package-lock.json`. Oxlint is the
Vite scaffold's linter; no additional lint framework or UI library was introduced.
Inter is self-hosted through Fontsource. No remote runtime assets are required.

See the [sprint plan](../docs/ai-sdlc/plans/UI-UX-SPRINT-001.md) and
[learning notes](../docs/learning/UI-UX-SPRINT-001-EXPLAINED.md).
# UI-04: run the connected assistant workflows

Keep the existing private Auth environment configuration. Start the backend in one terminal:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn assistant_builder.main:app --reload --host 127.0.0.1 --port 8000
```

From the repository root, in another terminal:

```powershell
cd frontend
npm.cmd run dev
```

Open http://127.0.0.1:5173/login, sign in, create two assistants, edit one,
save, reload, and confirm the other is unchanged. Sign out and switch accounts:
the previous owner's assistants must not appear. These actions persist real drafts
in the configured backend database. No new migrations or privileged browser keys are needed.

Vite forwards same-origin `/api/assistants` requests to local FastAPI `/assistants`.
The browser supplies the current Auth access token; it never supplies `owner_id`.
Production hosting must provide the equivalent same-origin `/api` reverse proxy;
`vite preview` alone does not provide this development proxy.
Knowledge integration remains UI-05; Playground and publishing remain deferred.
