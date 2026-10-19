# UI/UX Implementation Sprint — Owner frontend

Status: UI-03 live Auth review accepted by the developer on 2026-10-18. UI-04 implemented; final verification recorded below. Stop for review before UI-05.
Date: 2026-10-14. Sequence: after completed Phase 2, before planned Phase 3.

## Purpose and sources

Deliver a responsive owner interface for existing assistant and knowledge workflows.
This is a delivery-order change, not new product scope. Sources: approved intent,
SPEC-001 FR-001–003, NFR-001–002, AC-001–007/018; PLAN-001; accepted ADR-001–005;
Phase 0/2 contracts; actual `api.py`, `schemas.py`, `auth.py`, `knowledge_api.py`,
`knowledge_service.py`, `config.py` and `main.py` under `backend/src/assistant_builder/`.
Phase 2 completion evidence remains valid. No RAG, generation, publishing or visitor
conversation functionality is implemented in this sprint.

## Design review and scope reconciliation

[Figma source](https://www.figma.com/design/v4IxDkJNsw2k2LKkwfcR2e/Untitled?node-id=2-42505).
The linked node is the **Account form**, not the whole application. Page metadata
was inspected; high-fidelity context and screenshots were inspected for the form,
active dashboard, configuration, knowledge upload, deletion dialog and mobile dashboard.

| Design reference | Node | Planned use |
| --- | --- | --- |
| Login / account form | 2:42474 / 2:42505 | Email/password entry and shared auth controls |
| Sign up | 2:42534 | Registration; inspect full context before implementation |
| Active / empty dashboard | 2:42598 / 2:42769 | Owner assistant cards and first-assistant state; inspect empty-frame details next |
| Assistant configuration | 2:42851 | Editable fields, saved/dirty states and appearance sample |
| Knowledge upload / delete confirmation | 2:43029 / 2:43865 | Upload area, rows, statuses and confirmation dialog |
| Mobile dashboard | 2:44159 | Responsive navigation and stacked cards, 390px reference |
| UI kit | 2:44340 | Button/input/status tokens; inspect full context before extracting assets |

Observed visual direction: Inter typography, purple primary (`#635BFF`), white
cards, pale backgrounds, muted borders, rounded inputs, desktop sidebar and mobile
navigation. Preserve these visual relationships while adapting unsupported content:

| Figma content | Contract difference | Proposed treatment |
| --- | --- | --- |
| Google login / forgot password | Social login and password recovery excluded by ADR-002 | Omit these actions; email/password registration, login and logout only |
| Pro workspace, plan management, workspace switcher | No billing/team/workspace APIs or requirements | Use neutral owner navigation; omit billing/switching |
| Conversation metrics, resolution rate, visitor names, published cards | Future or out-of-scope data | Omit metrics/recent conversations; show real assistant list/count and returned draft state |
| Role selector plus separate purpose/description | API has one free-text `role`, no description field | One role textarea; do not silently combine fields or add schema fields |
| Fixed tone/style choices | API stores free strings, including existing custom values | Editable values; suggestions optional, never overwrite unknown existing values |
| Primary/accent colors | API accepts `colors: dict[str,str]`; tests establish `primary` only | Propose `primary`/`accent` UI mapping for review; preserve other keys on save |
| Chat-like appearance preview | No playground/widget backend yet | Optional static visual sample clearly labeled; no send button, generated response or latency promise |
| Ready status / “available in Playground” | Current state is `extracted`, no index yet | Label “Text extracted”; avoid implying RAG readiness |
| 62% processing progress / retry | No progress stream or retry endpoint | Indeterminate busy state; remove failed attachment then upload again |
| Delete changes answers immediately / permanent deletion copy | DELETE detaches draft, retains original for recovery | Explain removal from this assistant's draft; avoid promises about published answers or complete erasure |
| “Never used to train public AI models” | No approved provider-terms guarantee | Use only supported private-access copy; do not promise training policy |
| Playground, Publish & embed, Conversations/Inbox | Later-phase APIs absent | Disabled, labeled “Planned”; no fabricated activity or functional routes to missing APIs |

These are explicit adaptations to preserve approved requirements. Review them before
coding; visual fidelity does not authorize scope expansion. Download approved static
assets locally during implementation, never use temporary Figma URLs as runtime assets.

## Proposed stack and boundaries

The developer approved React + TypeScript + Vite and UI-02 on 2026-10-14.
A small SPA now lives in `frontend/`, alongside `backend/`. FastAPI remains the backend.
No SSR or second backend is needed for the current authenticated dashboard scope.

| Proposed dependency | Reason |
| --- | --- |
| React / React DOM | Reusable screens, form and request state |
| React Router | Nested assistant routes and protected navigation |
| Supabase JS | Existing Supabase Auth session lifecycle only |
| Vite, TypeScript, React Vite plugin and type packages (dev) | Build, development proxy and type checks |
| Vitest, Testing Library, user-event and DOM test environment (dev) | Form, request-state and interaction tests |
| Playwright (dev) | Browser navigation, responsive layout and end-to-end checks |

Use CSS custom properties/CSS modules for design tokens, native fetch for API calls,
and React state/context for forms/session. No Tailwind, Redux, Axios, component suite,
form library or server-state library initially. Reassess only if concrete complexity
warrants it. Pin compatible versions and commit one frontend lockfile during implementation.
Package versions, Node support and exact test scripts must be verified at setup.

Request flow: browser form → typed API module → FastAPI owner verification → existing
service/repository → SQLAlchemy + forced RLS. Only Auth requests go directly to
Supabase Auth. No browser table queries or direct Storage uploads/deletes.

### Authentication, tokens and origins

- Supabase JS handles email/password sign-up/sign-in/sign-out. A successful sign-up
  may have no session when email confirmation is enabled; show the current Auth
  result without changing project settings or claiming the user is logged in.
- Recommend SDK-managed session persistence in sessionStorage for the MVP (tab-scoped),
  subject to review. No custom token cookies or duplicate token stores. Browser
  storage is not XSS-proof: render user/file text as text, never arbitrary HTML.
- Send the current access token as Bearer to FastAPI. Route guards are UX only;
  FastAPI and RLS remain authoritative. Never send `owner_id`, provider/model options,
  database URLs, Storage keys, service-role keys or migration credentials.
- On logout/account switch clear owner data, cancel pending reads and ignore stale
  responses. On 401 allow SDK refresh handling, then require login if still invalid;
  do not automatically replay uploads/creates after uncertain outcomes.
- Proposed public frontend settings: `VITE_SUPABASE_URL`,
  `VITE_SUPABASE_PUBLISHABLE_KEY` (or existing anon key, never secret/service_role),
  and `VITE_API_BASE_URL`. All VITE settings are browser-visible. Frontend env loading
  must be isolated from `backend/.env`.
- Current FastAPI has no CORS middleware. Prefer Vite dev proxy `/api` → local
  FastAPI, stripping `/api` before forwarding so existing backend paths stay intact.
  This is a frontend development mapping, not a new API prefix.
- Production origin/hosting remains undecided. Recommend same-origin routing for
  the static frontend and API. If separate origins are chosen later, review an
  exact CORS allowlist for needed methods and Authorization/Content-Type headers;
  do not add wildcard credentials or change backend configuration now.

## Screen and API contracts

UI-03 routing adjustment approved on 2026-10-17: `/` is reserved for the future public
marketing page (minimal placeholder only). `/assistants` is the authenticated owner
dashboard; `/assistants/new` and `/:id/configuration` / `/:id/knowledge` beneath it
are protected placeholders. `/login` and `/register` implement Auth. `/dev/dashboard`
retains the original UI-only preview in development builds; it is excluded from
production. No assistant or knowledge data is fetched or fabricated.

| UI operation | Existing operation | Success / handling |
| --- | --- | --- |
| Auth | Supabase Auth SDK, not FastAPI `/auth/*` | Real Auth results; no invented backend routes |
| List assistants | GET /assistants | 200 array, including empty list |
| Create | POST /assistants | 201; submit all required configuration fields |
| Open configuration | GET /assistants/{assistant_id} | 200; missing/wrong owner 404 |
| Save draft | PATCH /assistants/{assistant_id} | 200; changed fields only, omit unchanged fields, never null |
| Upload | POST /assistants/{assistant_id}/knowledge-files | One multipart `file`, 201 with extracted state |
| List files | GET /assistants/{assistant_id}/knowledge-files | 200 metadata array; failed attached files remain visible |
| Download | POST /assistants/{assistant_id}/knowledge-files/{file_id}/download-url | 200 URL and expires_in; default 60 seconds, immediately offer/open link |
| Remove | DELETE /assistants/{assistant_id}/knowledge-files/{file_id} | 204 no JSON body; refresh list only after confirmed success |

There is no assistant DELETE, bulk upload, extraction retry, text-preview, progress,
playground, publish or conversation endpoint to call in this sprint.

Create requires `name` (1–120), `role` (1–500), `response_style` and `tone` (1–100),
`fallback_message` (1–500); `colors` defaults to an empty map. Display/submit real
values; no silent invented defaults. Name-only creation is incompatible with the
API: collect required configuration on the create screen, then upload knowledge.
Knowledge associations use file endpoints, not extra fields in assistant PATCH.
Preserve unsaved input on errors; “Save & continue” navigates only after success.

Knowledge validation: PDF/DOCX extension, nonempty, <=10,000,000 bytes, <=5 current
attachments including failures. Server checks remain authoritative. Start with one
file per action. Show filename, size, created timestamp, state and safe error copy.
Busy/processing status is not a percentage. Refresh metadata after every upload
outcome, including 422/503/network interruption, since a failed slot may persist.
Do not automatically retry a POST after timeout; first reconcile the list with the
owner. Removal does not cancel a remote upload or guarantee immediate physical erasure.

Normalize errors: 400 malformed upload, 401 session, 404 unavailable resource,
409 limit/state conflict, 413 size, 422 field/document validation, 503 unavailable,
and generic network/5xx. Render readable errors without raw stack traces/secrets.
Do not confuse assistant validation 422 with document validation 422. Never log or
persist signed URLs; explain expiry and request a new link on an explicit retry.

## Sprint file responsibilities (UI-02 subset created; integration remains planned)

- `frontend/package.json`, lockfile, Vite/TypeScript configs: isolated build/tooling.
- `frontend/.env.example`: public configuration placeholders only.
- `frontend/src/app/`: routes, session provider, protected shell and error boundary.
- `frontend/src/api/`: typed assistant/knowledge requests and normalized errors.
- `frontend/src/auth/`: Supabase client and session integration.
- `frontend/src/features/auth/`, `assistants/`, `knowledge/`: screens/forms/hooks.
- `frontend/src/components/`: Button, Field, Textarea, StatusBadge, Card, Alert,
  EmptyState, LoadingState, ConfirmDialog, Sidebar/MobileNavigation and FileRow.
- `frontend/src/styles/` and `assets/`: reviewed tokens, responsive layouts and
  locally downloaded design assets; avoid full-screen absolute-position exports.
- `frontend/tests/`: component/API integration tests and browser scenarios.
- README and `.gitignore`: setup/test commands and frontend build/secret exclusions
  during implementation. Backend changes only if an approved integration need arises.

## Incremental tasks, milestones and verification

Estimate: 4–6 focused implementation days, not a committed date. UI decisions and
remaining total project time need review. Each task ends with relevant checks before
the next; do not build the entire frontend in one unreviewed change.

| Task / milestone | Deliverable | Checks and traceability |
| --- | --- | --- |
| UI-01 Design/API reconciliation | Confirm stack, scope adaptations, color/session/origin choices; inspect remaining frames | Field-by-field mapping to FR-001–003; no unsupported requests |
| UI-02 Foundation and shell | Vite/TS app, tokens, reusable controls, desktop/mobile navigation | Build/type/lint checks, keyboard/focus tests, no frontend secrets; NFR-001–002 |
| UI-03 Auth | Registration/login/logout and protected pages | Invalid login, no-session registration, expiry and stale-data clearing; AC-002/018, ADR-002 |
| UI-04 Assistants | Create two assistants, list, edit, save/reopen draft configuration | AC-001–003/018, field limits, explicit null/owner override rejected, 404 behavior |
| UI-05 Knowledge | Upload/list/download/remove/replace with readable state | AC-004–007/002/018; 5-file/10-MB errors, failed-slot handling, signed expiry |
| UI-06 Review and handoff | Responsive/accessibility regression, test report and learning walkthrough | Visual comparison and approved deviations, integration suite, reviewer sign-off |

Testing layers:

1. Offline component tests with controlled API/Auth doubles: loading, empty/error,
   success, validation, disabled future controls, logout/race isolation, no duplicate
   create/upload replay. These do not prove Supabase RLS.
2. Browser tests against controlled responses: route refresh, dialog confirmation,
   keyboard focus restoration, unsaved form preservation and mobile interactions.
3. When separately authorized, real two-owner browser checks against existing APIs:
   create/configure/reopen, PDF/DOCX, temporary download, remove/replace, rejected
   cross-owner IDs. Reuse existing hidden local Auth tooling and scoped test cleanup.
   Do not run live mutations during planning; mocks alone do not close integration.
4. Backend pytest regression if backend or integration assumptions change. Preserve
   the documented local-PostgreSQL skips rather than silently declaring them passed.

Proposed viewports: 390px and 1440px Figma references, plus 320px and 768px adaptation
checks. Forms/cards must reflow without horizontal page overflow; mobile navigation
must not cover controls. Inputs have labels, errors linked to fields, visible focus,
keyboard operation and accessible busy/error announcements. Use design tokens while
checking text contrast and allowing zoom. These are sprint verification checks,
not new numbered SPEC requirements. Mobile configuration/knowledge layouts not
explicitly inspected in Figma require responsive interpretation and visual review.

Sprint exit: in-scope browser flows and integration evidence reviewed, no secrets
in build/logs, documented visual deviations and test gaps, and a phase-learning
report under `docs/learning/UI-UX-SPRINT-001-EXPLAINED.md`. Keep existing phase reports.
Resume Phase 3 only after review/authorization; its model/embedding/dimension and
threshold validation items in ADR-004 remain intentionally unresolved.

## Decisions for developer review

- React/TypeScript/Vite stack and UI-02 scope approved on 2026-10-14.
- The sprint and documented Figma scope adaptations are approved (especially role/description, omitted
  social login/metrics, noninteractive appearance sample and deferred navigation).
- Confirm `colors.primary`/`colors.accent` mapping and preservation of unknown keys.
- UI-03 follows the planned SDK sessionStorage approach; production origin/hosting can remain
  deferred until deployment. Existing Auth email-confirmation behavior must be
  inspected without changing settings when browser integration starts.
- Proposed UI language: English, matching Figma. RTL/localization is not assumed.
- Revisit the total timeline after this inserted sprint; no later phase is canceled.

UI-02 introduces frontend code and its necessary build/test dependencies only.
It does not amend SPEC/ADRs, implement Auth/API integration, change live Supabase,
start Phase 3, or authorize a commit/push. UI-03 requires developer review first.

## UI-03 implementation record (2026-10-17)

- Approved routing adjustment above; Phase 2 remains completed and Phase 3 planned.
- Reviewed the new Figma copy `BzfdfMerOG9BoX28X4usvS`, Auth frames `2:42474` and
  `2:42534`. Reuse existing tokens/controls and downloaded local icons. Omit social
  login, password recovery, full-name collection and unsupported policy links.
  Static chat artwork is clearly illustrative; no Phase 3 interaction is implemented.
- Add pinned Supabase JS 2.118.0, public environment validation before bundling,
  SDK session persistence/refresh and events, safe error classification and protected
  owner subtree. Credentials are submitted to Auth only, never to a new backend route.
- Registration supports both session and no-session results without changing live
  confirmation policy. Password requirements are enforced by the configured Auth
  service; the UI validates email/nonempty password without inventing a new policy.
- Clear owner subtree immediately on logout, remount on owner change, ignore stale
  bootstrap/late logout events. No data cache or pending backend reads exist yet;
  future UI-04 requests must abort/ignore old-owner results as already planned.
- SDK sessionStorage is project-scoped. A credential-free logout marker and blocked
  SDK storage writes prevent failed logout from restoring old credentials locally.
  Explicit local sign-out avoids logging out every device; an unavailable revocation
  is reported. Existing access JWT validity until expiry remains an ADR-002 limitation.
- UI-03 supports FR-001, NFR-001/002 and the Auth boundary for AC-002/018. It does not
  independently reverify database RLS or complete assistant/file browser workflows.
- No live Supabase settings, backend files, migrations, commit or push are changed.
- Source docs: Supabase JS signUp, signOut, onAuthStateChange; changelog reviewed,
  including upcoming legacy TLS cipher deprecation (modern browser client).
- Final checks: typecheck, lint, build PASS; 30 component/store tests and 13 Chromium
  browser tests PASS, no skipped tests. SDK browser requests use controlled Auth HTTP
  responses; no live sign-in/registration or RLS test was executed. Production output
  excludes `/dev/dashboard`; secret-pattern scan and `git diff --check` passed.
- Visual review: login desktop 1440px and registration mobile 390px inspected; Auth
  layout tests also cover 320px. No external runtime asset URLs. The build reports a
  non-blocking ~520.6 kB JS chunk (~151.6 kB gzip); code splitting is deferred.

## UI-02 implementation record (2026-10-14)

- Inspected Figma context/screenshots for empty desktop dashboard `2:42769`, mobile
  dashboard `2:44159`, and UI kit `2:44340`. Local SVG provenance is recorded in
  `frontend/src/assets/README.md`. Preserve 240px sidebar, 72px header, purple/neutral
  tokens, Inter, rounded cards, and mobile bottom navigation.
- UI-02 scope: Vite foundation, strict TypeScript, React Router declarative nested
  routes, shared CSS-module components, accessible native mobile dialog, keyboard
  focus handling, empty/placeholder pages. No session or protected-route claim.
- Scope adaptations: neutral workspace, explicit preview banner, no fake account,
  metrics or assistant records; deferred actions disabled. At narrow widths guide
  cards stack and bottom navigation reserves space below content.
- Installed React/DOM, React Router, locally bundled Inter; Vite/TS/React plugin,
  scaffold Oxlint, Vitest/Testing Library/jsdom and Playwright for checks. Supabase JS
  and API modules remain UI-03+ work. No frontend environment file is needed yet.
- Milestones: UI-01 design/scope approval received; UI-02 completed and verified on
  2026-10-17; UI-03 through UI-06 remain planned. Phase 2 remains completed.
- Traceability: UI-02 supports NFR-001/002 and the navigation foundation for AC-018.
  It does not independently complete AC-001–007 or verify authorization/RLS.
- Verification and learning evidence: see `docs/learning/UI-UX-SPRINT-001-EXPLAINED.md`.
- Final checks: strict typecheck, Oxlint, production build passed; 13 component tests
  and 6 Chromium browser tests passed, no skips. Browser checks cover four widths,
  nested navigation, refresh, skip link, mobile focus cycling/Escape and resize.
  Desktop/mobile screenshots reviewed; no external runtime requests observed.
  Initial sandbox worker/teardown issues were resolved by rerunning with permission
  outside the sandbox; the successful final command exited 0.

## Documentation references

- [Vite guide](https://vite.dev/guide/) and [public environment variables](https://vite.dev/guide/env-and-mode).
- [Supabase sign-up/session behavior](https://supabase.com/docs/reference/javascript/auth-signup).
- [Supabase public versus privileged keys](https://supabase.com/docs/guides/getting-started/api-keys).


## UI-04 implementation record (2026-10-18)

- The developer confirmed the UI-03 live authentication experiment succeeded and authorized UI-04.
- Implemented assistant list/create/get/edit against existing FastAPI contracts. No backend changes or new dependencies.
- Current SDK session supplies the bearer token; owner/epoch checks before and after responses prevent stale-account results. Route unmount aborts requests. 401 clears the local owner session; writes are never automatically replayed.
- Configuration saves changed fields only. Unknown color keys remain intact. Required fields and maximum lengths match the backend. No owner ID, model controls, knowledge operations, or assistant deletion are exposed.
- Figma configuration frame 2:42851 informed the card/preview layout. Free-text role/style/tone preserve the backend's arbitrary strings; no invented enumerations or description field. Preview is explicitly noninteractive.
- Development uses a same-origin Vite /api proxy. Production reverse-proxy setup remains a deployment decision.
- Traceability: FR-001/002, AC-001/002/003/018 and NFR-001/002. The knowledge-association portion of AC-003 remains UI-05; browser mocks do not reverify PostgreSQL RLS.
- Automated results and learning walkthrough are recorded in docs/learning/UI-UX-SPRINT-001-EXPLAINED.md. Live assistant create/edit through the new frontend remains developer review; no live data was modified by this milestone.
- Stop before UI-05. No commit or push.
- Final UI-04 verification: typecheck/lint/build PASS; Vitest 37 passed; Chromium 14 passed, plus the affected editor test rerun after spacing refinement (1 passed). No skipped tests. Build chunk-size warning remains non-blocking. Sandbox worker startup/teardown issues required an unrestricted rerun; successful final tests exited 0.

## GitHub checkpoint review (2026-10-19)

- Checkpoint scope: UI-02 foundation, UI-03 authentication, UI-04 assistant workflows; UI-05 and UI-06 remain pending. Phase 2 backend remains completed; Phase 3 has not started.
- Fresh checks: production build (including TypeScript) and lint passed; 37 component/store tests and 14 browser tests passed, no skips. Sandbox worker startup/teardown failed initially; successful reruns outside the sandbox exited 0.
- Auth browser tests now mock assistant-list requests explicitly so they never depend on a running local backend. No application behavior changed in this checkpoint pass.
- Tests use controlled HTTP responses; this pass did not repeat live Supabase verification. The known production bundle-size warning remains.
- Commit scope excludes local environment files, generated artifacts, Docker configuration, local skill installations, and unrelated AGENTS.md edits. No live database changes.
