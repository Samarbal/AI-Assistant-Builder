# Owner frontend — UI-05 / UI-06

React + TypeScript + Vite with Supabase email/password authentication. Owner routes
are protected; assistant and knowledge API integration are implemented. Run FastAPI
for owner workflows. The public marketing page is not implemented.

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
- `src/knowledge/`: file listing, upload, signed download links and confirmed draft removal.
- `src/components/`: Button, ButtonLink, TextField, Badge, Card, Alert, EmptyState,
  LoadingState, and local design icons.
- `src/styles/`: Figma-derived tokens and global keyboard/layout defaults.
- `src/assets/`: local Figma SVGs and provenance notes.
- `tests/`: component contracts and Chromium responsive/navigation checks.

Routes: `/` reserved for future marketing (minimal placeholder), `/login`, `/register`;
`/assistants` is the authenticated dashboard. `/assistants/new` and
`/assistants/:id/configuration` are connected forms; `/assistants/:id/knowledge` manages files.
`/dev/dashboard` is an unauthenticated UI-only preview in development builds only;
it does not grant access to owner routes and is absent in production builds.

Authentication, assistant and knowledge workflows are functional;
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
Playground and publishing remain deferred.

## UI-05: knowledge files

Open an assistant, then its Knowledge tab. Choose/drop one PDF or DOCX and select
Upload file. Limits are five current attachments (including failed ones), and
10,000,000 bytes per file. The backend validates actual content; filename validation
in the browser does not establish that a document is safe or readable.

The list shows metadata and processing status. Use Refresh files for pending states.
Text extracted is not RAG readiness. Remove a failed attachment before retrying;
replace an existing file by removing it and uploading its replacement.

Download requests a short-lived link (60 seconds by default). Select Open private
download before it expires. Links are not saved to browser storage; do not share
or screenshot them. Removal detaches the draft attachment; it does not revoke an
already-issued link or immediately erase stored bytes.

Uploads have a 120-second client timeout; other knowledge requests use 20 seconds.
A timeout does not cancel server processing. Upload/removal outcomes refresh the
list automatically, including failures. If refresh also fails, operations are
blocked until a successful Refresh files. Mutations are never automatically retried.

Focused checks: `npm.cmd test -- tests/knowledge.test.tsx` and
`npm.cmd run test:browser -- tests/browser/knowledge.spec.ts`.
These use controlled responses and never modify live Supabase. For the Arabic
walkthrough, see [UI-05 learning notes](../docs/learning/UI-05-EXPLAINED.md).

## UI-06 review

Local review and checks passed. See [review and live smoke-test procedure](../docs/ai-sdlc/contracts/UI-06-REVIEW.md). Live frontend integration remains unverified by the automated checks. Brand colors use native color pickers; choose a swatch and save the draft.

## P4-06 publishing, history, and widget

Open an assistant and use its Publish or Conversations tab. Publishing sends the
current server fingerprint and published version for conflict detection. The embed
snippet contains only the public assistant ID. Visitor history uses owner-authenticated,
bounded cursor pages and never returns visitor tokens or private citation metadata.

The frontend build serves `public/widget.js` and the public `/widget` iframe route.
For local development, Vite proxies `/public/*` to FastAPI. In a split-origin
deployment, set `VITE_PUBLIC_API_ORIGIN` to the public FastAPI origin and set the
backend `WIDGET_ASSET_ORIGIN` to the exact origin serving this frontend. FastAPI
then permits only that origin on public chat routes, without credentialed CORS.
The customer website must use a different origin from the frontend/widget asset
host; the loader refuses same-origin embedding so the host cannot inspect the
tester-only iframe.
Public chat remains disabled unless the server demo gate is explicitly enabled.
Approved testers enter the demo code inside the iframe; it and the visitor token
remain in frame memory only.

Focused checks: `npm.cmd test -- tests/publishing.test.tsx tests/widget.test.tsx`,
`npm.cmd run test:browser -- tests/browser/publishing-widget.spec.ts`,
`npm.cmd run lint`, `npm.cmd run typecheck`, and `npm.cmd run build`.
