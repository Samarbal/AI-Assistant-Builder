# PLAN-001: AI Assistant Builder MVP

Status: draft

## Source and planning boundary

- Specification: `docs/ai-sdlc/specs/SPEC-001.md`
- Intent: `intent/ai-assistant-builder.md`
- Original timeline: approximately 4.5 weeks for implementation. The UI/UX sprint added on 2026-10-14 requires a revised schedule; no new overall completion date is committed.
- Backend direction supplied for planning: Python with FastAPI.
- This plan covers only the requirements and acceptance criteria in SPEC-001. Accepted ADR-001 through ADR-005 govern architecture; React/TypeScript/Vite and UI-02 were approved on 2026-10-14.
- SPEC-001 and this plan intentionally remain draft during implementation, as explicitly authorized by the developer. Their draft status is not an implementation blocker.

## Current sequence and dependencies (updated 2026-10-22)

Phase 0 → Phase 1 → Phase 2 **completed** → **UI/UX Implementation Sprint (UI-02–05 implemented; UI-06 local review complete; live smoke test and human review pending)**
→ Phase 3 **indexing, retrieval, RAG, and Playground implemented locally; final verification blocked by `generation_input_limit`**
→ Phase 4 **P4-01 through P4-07 implemented and locally accepted** → Phase 5 **planned**.

The developer requested a usable owner frontend before RAG/Playground. Existing
phase numbers, requirements, acceptance criteria and accepted ADRs remain intact.
UI-02 adds the frontend foundation. UI-03 adds Supabase Auth and protected owner
navigation; UI-04 connects assistant workflows and UI-05 connects knowledge management.
The root URL is reserved for future marketing. Review is required before UI-06.
See [UI-UX-SPRINT-001](UI-UX-SPRINT-001.md) for Figma review, API mapping, milestones,
proposed dependencies, tests and decisions requiring review.

## Proposed architecture summary

Use a small FastAPI backend organized around assistant ownership and published-versus-draft state. Keep external AI, persistence, file storage, and embedding concerns behind narrow interfaces so their concrete choices can be made through ADRs without changing the product behavior described by SPEC-001.

Expected components/modules:

- Account and ownership boundary: identifies the current business owner and scopes every assistant, knowledge file, conversation, and publish operation to that owner.
- Assistant management: create multiple assistants and edit name, role, colors, response style, tone, knowledge associations, and fallback message.
- Draft/published state: keeps editable changes separate from the public version until publish or update is requested.
- Knowledge management: accept PDF and DOCX uploads, list/view associated files, remove files, and support replacement through remove-then-upload.
- Retrieval and response orchestration: retrieve relevant business knowledge, apply the assistant configuration, and return the configured fallback when sufficient knowledge is unavailable. Provider and retrieval implementations remain replaceable.
- Playground: run conversations against the current draft configuration and knowledge without making playground use a publishing prerequisite.
- Publishing and embed delivery: publish an assistant and return a JavaScript embed snippet that targets the published assistant.
- Visitor conversations: record basic conversations, messages, and timestamps and expose owner-scoped list/detail views.
- HTTP/API boundary: expose owner workflows, playground requests, publish/update actions, embed retrieval, and visitor chat endpoints through FastAPI.
- Validation and error handling: validate ownership, file type, state transitions, malformed requests, unavailable knowledge processing, and failed response generation without exposing unrelated owner data.

No application code or infrastructure is created by this plan.

## Implementation phases

### Phase 0: Review and contract preparation (2-3 days)

Required MVP work:

- Draft-status clarification resolved by the developer: keep SPEC and PLAN draft during implementation.
- Convert the specification requirements and acceptance criteria into API/domain contracts and test fixtures.
- Confirm the concrete persistence, file-storage, retrieval, AI-provider, and authentication choices through ADR review before implementation.
- Define owner-scoped identifiers and draft/published state transitions.

Tests and traceability: establish test cases for FR-001, FR-010, NFR-001, NFR-002 and AC-001, AC-002, AC-010, AC-015, AC-016, AC-018.

### Phase 1: Owner-scoped assistant and configuration workflows (5 days)

Required MVP work:

- Implement account-context enforcement at the service boundary.
- Implement assistant creation, listing, independent management, and configuration persistence.
- Implement draft state for editable assistant configuration.
- Validate that core workflows do not ask the owner for model parameters or code.

Tests and traceability: FR-001, FR-002, NFR-001, NFR-002; AC-001, AC-002, AC-003, AC-018.

### Phase 2: Knowledge management and processing (5-6 days)

Completed on 2026-10-14 following developer approval and final review. See
`docs/ai-sdlc/contracts/PHASE-2-VERIFICATION-2026-10-14.md` for acceptance coverage,
live evidence, final test results and the non-blocking local-test limitations.
This phase ends at extracted text. Phase 3 has not started; plan status remains draft.

Required MVP work:

- Implement PDF and DOCX upload validation.
- Implement owner-scoped file listing and viewable file information.
- Implement removal and remove-then-upload replacement workflow.
- Add processing states and failure reporting so an unsuccessful file process cannot silently become usable knowledge.
- Connect processed knowledge to the assistant while keeping storage and retrieval implementations behind interfaces.

Tests and traceability: FR-003; AC-004, AC-005, AC-006, AC-007.

### UI/UX Implementation Sprint: owner frontend (planned, before Phase 3)

- Depends on completed Phase 1/2 APIs and accepted Auth/Storage boundaries.
- Prepare responsive Figma-based login/registration, assistant list/create/configure,
  and knowledge upload/list/download/remove flows; reusable controls and feedback.
- Integrate Supabase Auth and existing FastAPI routes only. Use the proposed
  React/TypeScript/Vite stack after review; install nothing in the planning turn.
- Deliver milestones in order: visual/API reconciliation; frontend shell; Auth;
  assistant workflows; knowledge workflows; responsive/accessibility/security tests.
- Playground, publishing/embed and conversations remain visibly deferred; no mock
  functionality or unsupported backend endpoint is introduced.
- Exit: reviewer accepts browser workflows, test results and learning report.
  Then resume Phase 3, including its unresolved provider/index validation items.
- Planning estimate: 4–6 focused development days, subject to design/stack review;
  re-baseline the original total schedule rather than silently compressing later work.

Traceability: FR-001–003; AC-001–007; NFR-001–002 and AC-018 for implemented workflows.
Future workflow acceptance remains owned by Phases 3–5.

### Phase 3: Response orchestration and optional playground (5-6 days)

Status: Phase 3 implementation is complete for the MVP workflow and ready for
review. Versioned indexing, semantic retrieval, RAG orchestration, authenticated
Playground API/UI, and indexing preparation controls are implemented. Retrieval
calibration succeeded with four known-answer and three unknown-answer questions;
the local `RETRIEVAL_MIN_SIMILARITY` is `0.30347`. A developer-reported live
frontend smoke test completed six consecutive Playground requests with HTTP 200.
This is limited verification, not evidence of broader reliability. Known
limitations include approximately 9–14 second Playground latency, no semantic
entailment guarantee from citation validation, and skipped PostgreSQL integration
tests when dedicated database configuration is unavailable. Metadata-only
`generation_input_limit` diagnostics now identify the rejecting stage and guard;
they have not yet been verified against a new live failure. No production
readiness or wider reliability claim is made.

Required MVP work:

- Implement playground chat against the current draft configuration and uploaded knowledge.
- Apply grounded-response behavior and the owner-configured fallback when sufficient relevant knowledge is unavailable.
- Ensure current draft changes are reflected in playground requests.
- Handle unavailable, malformed, or failed knowledge retrieval and response generation with a safe failure result that does not invent business-specific content.

Tests and traceability: FR-004, FR-005; AC-008, AC-009, AC-017.

#### Phase 3 incremental execution

Use the Phase 3 refinement in `contracts/PHASE-0-CONTRACTS.md` as the single
contract source; do not create another parallel implementation plan.

| Task | Deliverable and verification | Traceability |
| --- | --- | --- |
| 1 — contracts/provider validation | Independent-turn requests, readiness/failure rules, bilingual synthetic fixtures, offline oracle checks; conditional synthetic-only provider smoke test | AC-008/009/017/018 |
| 2 — deterministic chunking | Persisted text as input; token-aware 600/100 chunks, stable offsets/IDs, Unicode/Arabic cases, resource-limit rejection without silent truncation | AC-008/017 |
| 3 — additive schema/repositories | Index versions, owned chunks, active reference and budget-attempt ledger; dimension validated first; runtime-role RLS, concurrent claims, atomic activation/rollback; recovery baseline/reference review | AC-008; ADR-001/003/004 |
| 4 — preparation/embedding | Recommended explicit bounded preparation batches, persisted leases/idempotency, no SQL transaction across external I/O; test crashes, late responses, quota exhaustion, source changes, incompatible reindex | AC-008/017/018 |
| 5 — retrieval/generation | Exact cosine top-five, calibrated boundary, source-validated citations, no generator call for insufficient evidence; provider mocks and approved live synthetic checks | AC-008/009/017 |
| 6 — Playground UI/API | Current saved draft on every independent turn, readiness, preparation progress, safe errors, session isolation; no publishing/history | AC-008/009/018 |
| 7 — release review | Approved migration preflight, real PostgreSQL role/RLS checks, bounded two-owner integration verification, learning review | All above |

Phase 3 implementation update (2026-10-21): indexing persistence and the bounded
indexing service are implemented locally. The authenticated owner API now exposes
the contracted status and prepare routes, and the Knowledge tab provides explicit
one-batch preparation, progress, safe errors, and AI-credit disclosure. Frontend
status polling is read-only; each embedding batch requires an explicit owner action.
No live indexing/provider call, deployment, or migration was performed for this UI/API
work. The UI-06 live smoke-test gate remains pending. Phase 3 is not complete: work
remains for controlled preparation of this assistant, live retrieval and grounded
Playground verification, and final Phase 3 review.

Phase 3 progress update (2026-10-22): the developer-reported live retrieval
calibration completed with 4 known-answer and 3 unknown-answer questions. The
recommended threshold, `0.30347`, was applied to the local `backend/.env` only;
that file and local calibration artifacts are excluded from Git. Focused offline
retrieval/calibration tests passed (27 passed). No provider calls or database
changes were made during this local threshold update. Playground acceptance remains
blocked by the reported `generation_input_limit` error; Phase 3 is not complete.

Phase 3 final review update (2026-10-23): the implementation now emits sanitized
byte-size diagnostics for RAG packing and generation input-limit guards. The
diagnostic contains only stage, guard, question/top-chunk/evidence/assembled-prompt
byte counts, and configured limits; it excludes question text, document text,
embeddings, credentials, and generated answers. Limits and response behavior are
unchanged. Focused tests passed (66); the full offline backend suite passed (422)
with 28 PostgreSQL integration tests skipped because dedicated PostgreSQL test
configuration was unavailable. The known six-request HTTP 200 smoke result and
9–14 second latency are developer-reported; no live provider or database request
was made for this update. Phase 3 implementation is complete for review, with
broader reliability, latency improvement, and semantic entailment verification
remaining limitations rather than claims of production readiness. If
`generation_input_limit` recurs, inspect the sanitized stage/guard metrics before
changing limits or evidence handling. Frontend verification for this review:
Vitest 61 passed; lint, typecheck, and production build passed. All 23 Playwright
scenarios reported success, but the runner did not exit cleanly after the final
scenario and was interrupted during teardown, so browser-suite process completion
remains unverified. The production build retains the existing >500 kB JavaScript
chunk warning.

Task 1 recommendations (not accepted ADR amendments): explicit preparation endpoint
instead of message-triggered indexing; operational limits and budget accounting in
the existing contract. No new worker infrastructure. Approved foundations include
versioned atomic indexing, exact cosine, independent turns and validated citations.

Task 1 provider status: endpoint/key/model settings are absent; no external calls
made. Exact generation/embedding models, dimension, pricing, quota and numeric
similarity threshold remain unresolved. Named-provider synthetic-data approval and
secure credentials are prerequisites for live smoke testing. Do not assume
OpenAI-compatible means a particular model is available.

Task 2 gate: GO only for offline chunking work after human review and tokenizer
selection/justification; NO-GO for provider-backed indexing, dimension-specific
migration or production deployment until provider validation passes. The original
5–6 day estimate is not a validated estimate for the expanded indexing work.

Task 1 local verification (2026-10-20):
`python -m pytest tests/test_phase3_contracts.py -q -p no:cacheprovider`
passed 33 checks, zero skips. Scoped `git diff --check` passed. The checks validate
synthetic contract examples and adversarial counterexamples only, not working RAG,
API endpoints, provider quality, PostgreSQL RLS, or UI-06 live integration.
No application code/dependencies, migrations, live resources, commits or pushes.

Task 2 verification (2026-10-20): pure `Chunker`/`Tokenizer` interfaces and
deterministic source windows implemented; tiktoken 0.14.0 locked with provisional
cl100k_base encoding. No embedding model selected. See the Task 2 section of
`contracts/PHASE-0-CONTRACTS.md` for offsets, fingerprint and resource semantics.
Focused tests: 34 passed. Full offline backend regression: 179 passed, 27 skipped,
3 existing warnings. PostgreSQL suites were explicitly disabled; no live verification
claimed. `uv lock --check --offline` and scoped diff checks passed.
Learning: `docs/learning/PHASE-3-TASK-2-EXPLAINED.md`.
NO-GO for dimension-specific Task 3 migration until embedding provider/model,
dimension and tokenizer compatibility are validated. No schema or live changes.

### Phase 4: Publishing, embed delivery, and visitor chat (5-6 days)

Status: planned; follows Phase 3. Reuse sprint navigation without treating its
disabled future-feature entries as completed publishing or conversation features.

Required MVP work:

- Implement publish/update transitions from draft to public state.
- Verify that publishing can succeed without prior playground use.
- Generate and return a JavaScript embed snippet for a published assistant.
- Serve the embedded chat flow against the published version only.
- Record visitor conversations, messages, and timestamps.
- Provide owner-scoped conversation list and conversation detail views.

Tests and traceability: FR-006 through FR-010, NFR-003, NFR-004; AC-010 through AC-016.

#### P4-01 contracts and security design (2026-10-23)

Status: P4-01 documentation/design completed and approved. P4-02 and P4-03 local
work are recorded below; no live migration is authorized. P4-04 public chat is
implemented locally and awaits human review. Public access remains disabled by
default, with no live Supabase changes or provider calls. The human
approved the separate restricted public DB runtime, durable shared AI reservations,
initial pricing-dependent $0.01/message, $0.10/index and $1/day limits, zero-file
fallback publishing, blocking processing/failed attachments, 24-hour visitor tokens,
independent turns, no raw public citations/filenames/excerpts, isolated iframe loader,
and rejection of in-flight replies after a published-version change without retry.

The Phase 4 section of `../contracts/PHASE-0-CONTRACTS.md` holds the concrete route
contract, role/column-grant/RLS matrix, accounting function interface, snapshot and
cleanup locking invariants, token lifecycle, cost-reservation rules and P4-C01
through P4-C07 test mapping.
These refinements supersede the corresponding open recommendations in the original
proposal below. They do not claim implementation, database verification or pricing
verification. Existing Phase 3 provider adapters and private Playground remain intact.

The conditional security approval has been translated into the role/grant/RLS/function
design in the contracts and addenda to ADR-001/002/005. No security architecture
decision remains unresolved for P4-01. The following P4-02 sequence is prepared for
implementation review; it does not authorize migrations or live database access.

P4-02 implementation sequence:

1. **Schema and lock contract:** prepare additive publication, immutable snapshot/source,
   conversation/turn and accounting objects; composite ownership/reference constraints,
   idempotency rules and indexes. Verify schema prerequisites read-only only under
   separate authorization. Review offline SQL for no cascades, mutable activated
   snapshots, PUBLIC/Data API grants, or changes to existing owner grants.
2. **Roles and RLS:** provision separate public login and NOLOGIN function owner with
   explicit attributes/no memberships; apply exact schema/table/column grants and
   forced RLS. Create four fixed-signature functions, revoke PUBLIC EXECUTE in the
   migration transaction, grant EXECUTE only to runtime logins, and enforce a pinned
   safe search_path with qualified names. Catalog tests prove neither runtime can
   access ledger rows directly and function owner cannot access tenant tables.
3. **Budget functions:** implement operation/attempt/UTC-day reservations with integer
   micro-USD, operator-managed price versions, atomic locks, caller-role binding,
   idempotent reserve/dispatch/settlement, bounded input/output ceilings, conservative
   day rollover and uncertain-charge retention. Concurrency tests race at/over all
   caps; replay cannot dispatch twice; unknown pricing and ledger errors block provider
   calls; dispatched uncertainty is never refunded automatically.
4. **Snapshot repository/service:** freeze saved configuration and complete ready
   source manifest in one transaction. Zero files produce fallback-only snapshots;
   processing/failed files reject. Validate expected fingerprint/version, lock parent
   and files in a stable order, activate atomically, and preserve previous versions.
   Injected failures preserve the old active pointer; concurrent edits/publishes have
   a consistent winner; idempotent replay creates no duplicate; activated content and
   references reject mutation.
5. **Recovery compatibility:** extend the exact schema/column guard and recovery logic
   with snapshot references in the same change. Cleanup claims and reference checks
   serialize with publishing; cleanup cannot remove an artifact retained by any
   snapshot; publishing rejects claimed/missing sources. Crash/race tests verify
   recovery remains fail closed. No snapshot garbage collection is enabled.
6. **Real PostgreSQL verification:** run dedicated tests under actual
   `assistant_runtime`, `assistant_public_runtime`, and function-owner execution
   contexts. Cover role attributes/memberships, direct ledger denial, function grants,
   RLS, pool reuse after commit/rollback, reservation concurrency/rollover, snapshot
   immutability, atomic activation, and cleanup races. No skipped security test counts
   as passing; mocks cannot establish role/RLS behavior.

P4-02 implementation is local unless separately authorized. Provider pricing, billing
semantics and quota must be verified before production price rows or paid dispatch;
the approved caps remain conditional. Any inability to prove PostgreSQL role/RLS
behavior blocks public enablement. No migration, Supabase connection, AI call or
application test occurred during P4-01.

P4-03 local implementation update (2026-10-23): authenticated owner routes now expose
publication status, atomic publish/update through the existing snapshot service, and
an embed snippet containing only the stable opaque public ID. The snippet requires a
validated `WIDGET_ASSET_ORIGIN`; unset or unsafe origins fail closed. Public chat and
widget delivery remain disabled. The shared accounting schema/functions remain in
place, but provider-dispatch reservation/settlement integration is deferred by human
decision and is a mandatory gate before unrestricted public launch. This deferral
does not enable unrestricted paid access: no public AI route is registered. The
P4-03 API-focused suite passed 10 tests. A fresh disposable pgvector/pg16 database
passed 35 real PostgreSQL tests across Phase 1/2/P4, including owner isolation,
atomic publication, replay/deduplication, snapshot immutability and rollback. The
full offline backend suite passed 433 with 36 opt-in PostgreSQL cases skipped. The
test container was removed afterward.

P4-04 local implementation update (2026-10-23): added a separate public runtime
engine with a fail-closed role/grant check, immutable active-snapshot resolver,
snapshot-pinned pgvector retrieval, internal citation validation, no-store public
assistant/conversation/message endpoints, 24-hour hashed visitor capabilities,
durable pending/final turn states, idempotent replay, in-flight version rejection,
and bounded request/rate/concurrency guards. Public routes require both the
`PUBLIC_CHAT_ENABLED=true` switch and one or two server-provisioned demo access
tokens whose SHA-256 digests are configured in `PUBLIC_DEMO_TOKEN_SHA256`; the
default remains disabled. They use `PUBLIC_DATABASE_URL` only and never fall back
to the owner or migration connection. Testers send `X-Demo-Access` and use the
returned `X-Visitor-Token` capability; tokens are not logged or persisted in raw
form. The widget and owner history UI remain unimplemented. Offline public/P4-03
tests passed 19 tests; the complete P4 PostgreSQL integration module passed 10 tests
on disposable local pgvector/PostgreSQL 16, including public-role RLS, denial of
draft/ledger reads, fallback-only chat, 24-hour conversation creation, idempotent
replay, and conflicting request rejection. No external provider calls were made.
The full offline backend suite passed 442 tests with 38 opt-in PostgreSQL tests
skipped; compilation passed. The skipped tests were not counted as passing.

The shared budget-dispatch integration remains deferred by the explicit demo
decision. The demo allowlist and in-process limits are access/abuse controls, not a
durable monetary cap. Do not enable unrestricted public traffic or multiple app
workers. Before public launch, integrate shared reservations/settlement for
embedding and generation, verify provider pricing/quota, provide shared rate and
concurrency controls across workers, and complete public security/quality and live
smoke reviews. Public chat remains disabled unless an operator explicitly configures
the allowlist and switch for the bounded demo.

P4-05 local implementation update (2026-10-23): owner routes now expose
`GET /assistants/{assistant_id}/conversations` and
`GET /assistants/{assistant_id}/conversations/{conversation_id}` over the P4-04
tables; no migration or duplicate persistence was added. Both routes require the
existing verified Supabase owner context, explicit owner/assistant predicates, and
the existing forced-RLS runtime transaction. List and detail pages default to 20
rows and cap at 100. Stable cursors use timestamp plus UUID ordering. Conversation
summaries fetch only the newest turn per conversation, avoiding an unbounded turn
count scan. Detail returns
user and assistant messages, timestamps, safe turn status/outcome, and the immutable
published version number. It never selects or projects visitor-token hashes, input
hashes, request IDs, internal failure codes, or owner/publication/snapshot metadata.
Cross-owner and cross-conversation identifiers return the same 404. Database errors
map to a generic 503 without exception details. The existing unique per-conversation
request ID remains the idempotency boundary; history reflects the single committed
turn and retains its original snapshot version after republishing.

Verification: focused history unit and API tests passed 11 tests; the P4 real
PostgreSQL integration module passed 11 tests against disposable local PostgreSQL
16/pgvector, including owner and conversation isolation, list/detail cursor paging,
idempotent replay, and old/new snapshot-version history. Full offline backend suite:
453 passed, 39 opt-in PostgreSQL tests skipped; compileall passed. The dedicated P4
PostgreSQL module was run separately and passed, so its security checks are not
counted among the skips. No live Supabase or AI provider was used. P4-05 is locally
implemented and awaits human review; P4-06 remains the owner publishing/history UI
and widget task.

P4-02 local implementation update (2026-10-23): additive Alembic revision
`0006_publication_budget` and SQLAlchemy publication records are implemented locally.
Snapshots are insert-only; the publication row's active-snapshot pointer is the
atomic activation boundary. Source references are insertable only in the snapshot's
creation transaction, with deferred manifest/index checks. Knowledge cleanup now
refuses files referenced by any published snapshot. Recovery checks the expected
P4 table/column set, forced-RLS flags, role attributes, and direct ledger grants; it
does not fingerprint every policy/function definition. The migration provisions the
restricted public role and SECURITY DEFINER shared budget functions. Public chat,
widget, and runtime budget-call integration remain disabled/deferred. No live
Supabase migration or provider calls were made. At P4-02 completion, the disposable
local PostgreSQL suite passed 34 tests across Phase 1, Phase 2, and P4; that offline
suite run passed 423 with 35 opt-in PostgreSQL cases skipped.
Public chat/widget and application-side reservation/settlement integration are
separate later work and remain disabled until reviewed.

#### Original Phase 4 review proposal (2026-10-23; superseded where noted above)

This section refines the existing phase, not its product scope. The original
5â€“6 day estimate is provisional: public authorization, persistent cost control,
and recovery compatibility must be reviewed before committing to a delivery date.
API proposals are in the Phase 4 section of `../contracts/PHASE-0-CONTRACTS.md`.
SPEC-001 and accepted ADRs remain unchanged. All decisions below not already in
those sources are recommendations, not approved architecture amendments.

Readiness and reuse:

- Reuse SQLAlchemy/session lifecycle, authenticated owner services, forced owner
  RLS, immutable extracted text, versioned ready indexes, query embeddings, exact
  cosine retrieval, `AnswerGenerator`, local fallback, and citation validation.
- `retrieval.py` reads `assistants.active_knowledge_index_id`, compares the current
  attachment manifest, and excludes `removed_at` files. `rag.py` reads current
  assistant behavior and checks draft freshness. Neither is a public-snapshot
  execution path; exposing the Playground route anonymously would be incorrect.
- The owner `DATABASE_URL` role and `set_owner_identity` are for verified owners.
  There is no reviewed visitor database scope, public role, or published resolver.
- `knowledge_recovery.py` checks exact table/column baselines and requires a draft
  parent. It currently deletes recorded removed originals without snapshot-reference
  checks. Extending the baseline alone is unsafe: add reference protection first.
- Reuse React routes, API/auth handling, colors, feedback controls, and chat visual
  patterns. Publishing, conversation screens, public routes, and widget assets are
  not implemented in `frontend/src/app/routes.tsx` / backend route registration.
- Current configuration/adapters bound requests but do not supply a durable global
  chat budget or public limiter. The contract's $1/day limit remains unenforced;
  indexing's $0.10 reservation is not a global spend guard.
- Prior verification: 422 backend tests passed, 28 PostgreSQL tests skipped;
  frontend 61 tests passed, lint/typecheck/build passed. Browser scenarios reported
  23 successes but clean teardown was not verified. These are prior results, not
  tests executed during this planning review. Six live HTTP 200 requests and
  9â€“14 second latency are developer-reported; neither proves public readiness.

Proposed architecture and flow:

1. Owner publish request â†’ existing verified owner context â†’ publishing service â†’
   locked, consistent draft/configuration/knowledge read â†’ immutable snapshot plus
   durable source/index references â†’ atomic active-public-pointer update â†’ snippet.
   Publish performs no AI calls. It never checks Playground-use history.
2. Public widget â†’ separate public router â†’ body/rate/concurrency checks â†’ published
   resolver â†’ conversation capability check â†’ cost reservation â†’ query embedding â†’
   snapshot-bound cosine search â†’ existing evidence packing/generation/validation â†’
   response/history commit. No SQL transaction is held across provider I/O.
3. Owner history â†’ verified owner context â†’ owner-scoped conversation repository â†’
   bounded list/detail responses. History is required by FR-009/AC-013â€“014, not a
   future optional addition. Search, analytics, export, identification and scheduled
   deletion remain excluded.

Draft/published persistence proposal (conceptual only; no migration authored):

- Keep the existing draft row/state and draft active-index pointer. Add a separate
  public mapping with a random stable public ID and active published-snapshot
  reference; do not overload `Assistant.state` or the draft index pointer.
- A snapshot freezes name, colors, behavior/fallback, source manifest, ready index
  reference, embedding-space identity, and calibrated retrieval policy. API keys
  and provider endpoints stay in environment configuration. Changing embedding
  configuration must not silently reinterpret vectors pinned by old snapshots.
- Retain a snapshot-to-file/index reference manifest with frozen source labels.
  Reuse immutable chunks/vectors; no duplicate embedding calls on publication.
  Enforce same-owner/same-assistant relationships and reject references to building,
  failed, incompatible, or partially complete indexes. Protect published content
  from UPDATE/DELETE and retained artifacts from cascading deletion.
- For attached eligible knowledge, require a ready matching index before publish;
  return a clear readiness conflict otherwise. Recommend allowing a valid draft
  with zero attachments to publish as fallback-only (no provider calls). This
  interpretation of AC-010 requires confirmation; no silent partial-file publish.
- Publish uses expected draft fingerprint, expected active-public version, and an
  idempotency key. Concurrent saves/removal/preparation/publish use a consistent
  parent/file locking order; stale input returns conflict. Snapshot insertion,
  references and pointer activation share one transaction. Failure preserves the
  old public version; replay does not create duplicate snapshots.
- Public retrieval selects only the index/source set pinned by the published
  snapshot, independent of current draft attachments or draft active pointer.
  Draft removal/reindex must not invalidate published behavior (AC-015).
- Each message pins one active snapshot. Recommend rejecting an in-flight reply
  with `published_version_changed` if publication changes before final commit;
  never mix versions or automatically regenerate. Recheck under the public mapping
  lock when committing the reply. Each subsequent message resolves the new version.
- Basic history needs owner/assistant-scoped conversations and ordered messages
  with server UTC timestamps, request-id uniqueness, outcome/status and snapshot
  references. A random conversation capability identifies a session, not a person.
  Recommend independent generation turns while displaying/storing the conversation;
  model conversational memory is not added without a separate requirement decision.

Security and cost proposal:

- Recommend a separate restricted `assistant_public_runtime` connection/role for
  public handlers in the same FastAPI process. It may resolve public mappings,
  read approved snapshots and their pinned chunks, and write narrowly scoped
  conversation turns. It cannot read drafts, private original-file metadata/text
  tables, Storage objects, or owner histories, or publish/edit/index anything.
  The design addenda to ADR-001/002/005 are now recorded; schema implementation
  still requires separate authorization.
- Preserve owner role checks and forced RLS. New public RLS predicates are bound
  to server-resolved public assistant/snapshot and validated conversation context,
  not a caller-provided owner ID. Missing/invalid context fails closed; no policy
  with unconditional public access, admin/service-role DB connections, or owner
  impersonation. Test actual separate runtime logins and connection-pool reuse.
  Transaction-local context is trusted application context, not protection from
  arbitrary SQL execution under the same role. Exact grants/policy design is recorded
  in the P4-01 contract and ADR addenda.
- Deny ordinary Supabase Data API access to all application tables; keep private
  Storage and signed downloads owner-only. A public ID is visible and copyable,
  never an owner authorization credential. Public responses use a strict projection.
- Keep the ADR's configurable 30 requests/minute per IP/public-assistant pair;
  supplement with bounded global/per-assistant concurrency, bounded limiter-key
  lifetime/cardinality, request-body caps, and a server-side public-chat kill switch.
  Trust forwarded IP headers only from configured proxies. One instance/worker is
  required for consistent in-process limits. Reject before provider dispatch;
  never rely on CORS, Origin headers, opaque IDs, or a copied snippet to stop bots.
- Before public enablement, implement a durable atomic budget reservation shared
  by indexing, Playground and public chat. Recommend retaining proposed $0.01 per
  message (query + generation), $0.10 per index, and $1/day total until reviewed.
  Reserve worst-case cost before each dispatch, reconcile validated usage, retain
  uncertain spend, reject if pricing/quota is unknown, and disable automatic retries.
  Use a minimal accounting boundary containing only counters/reservation IDs, not
  tenant content; exact grants for shared accounting require approval. Do not relax
  owner-data RLS to obtain a global total. In-memory counters or a manually watched
  demo budget are insufficient for unattended public traffic. Provider-side caps,
  where available, supplement application estimates; estimates are not invoice guarantees.
- Bound full request duration across embedding/generation/persistence; existing
  two 12-second provider deadlines alone do not implement a shared request deadline.
  Failures remain distinct from insufficient evidence. No generation call when
  evidence is insufficient; return the snapshot's exact fallback with no citations.
- Source-membership validation does not prove factual entailment. Preserve limits
  and prompt-injection defenses; validate representative contradictory/irrelevant
  evidence and Arabic examples before public enablement. Keep content out of logs.

Widget and owner UI proposal:

- Add Publish/Update and embed-copy UI within the existing assistant layout, showing
  readiness, changed draft, publication success/conflict and public-visibility notice.
  Add the already-required owner conversation list/detail screens.
- Serve `widget.js` and the `/widget` iframe route from the existing React/Vite
  frontend. FastAPI serves only its public chat API and applies exact-origin,
  non-credentialed CORS to that public route family using `WIDGET_ASSET_ORIGIN`.
  The loader reads only the opaque public ID; owner tokens and model configuration
  never enter the widget. This packaging/CORS boundary is approved in ADR-005's
  P4-06 addendum.
- Frame fetches the public API without owner credentials; no dependency on third-party
  cookies. Keep conversation capability in frame memory, never in the snippet or
  URL/logs. Validate any postMessage source/origin and expose no history/content to
  the parent page. Apply frame/CSP policy specifically to widget pages, keeping owner
  pages protected. Do not apply permissive credentialed CORS to owner APIs.
- Render response/citation text as plain text, validate colors, avoid injected HTML,
  provide keyboard/focus handling, mobile layout, RTL, pending/fallback/error states
  and a disabled duplicate-submit control. No automatic AI retry or streaming in
  this proposal. Restrictive host CSP may require host deployment changes; do not
  promise universal operation where external scripts/frames are explicitly blocked.
- Recommend public answers omit private filenames, file/chunk IDs, raw excerpts,
  storage paths, similarity scores, internal errors and provider usage. Internal
  citation validation remains mandatory. Public citation display needs a deliberate
  disclosure decision because SPEC does not require raw source exposure.

Ordered implementation tasks (each stops at its verification boundary):

| Task | Deliverable and objective acceptance/tests | Traceability | Rollback |
| --- | --- | --- | --- |
| P4-01: contracts and security design | Record approved public-role grants/RLS, accounting boundary, API projections, snapshot race semantics and disclosure decisions. Implementation tests are specified for P4-02 and later. | AC-002/010â€“018; ADR-001/002/005 | Documentation only; no public routes enabled. |
| P4-02: snapshots and recovery compatibility | Additive migration proposal, immutable publication/reference records, composite ownership constraints, narrow privileges. PostgreSQL tests prove atomic pointer change, failed publish preservation, immutable snapshots and owner isolation; cleanup refuses every retained reference and detects unknown schema. | AC-002/015/016; ADR-003/005 | Keep additive schema and data; disable publishing/cleanup, never destructive downgrade. |
| P4-03: publish service and owner API | Publish without Playground use, no AI calls; expected fingerprint/version conflicts and idempotent replay; readiness failures preserve current public snapshot. Repeated/concurrent publish creates no duplicate activation. | AC-010/011/015/016/018 | Disable publish writes; retain current public pointer. |
| P4-04: gated public snapshot chat | Separate restricted public runtime; demo allowlist and disabled-by-default gate; public assistant/conversation/message contracts; snapshot-pinned retrieval/generation; internal citations but no private citation projection; 24-hour visitor capability, idempotency, rate/concurrency/body/deadline bounds, failure-safe finalization and version-change rejection. Tests prove no draft reads, fallback without provider calls, replay behavior and active-snapshot pinning. Shared spend reservations remain intentionally deferred for the bounded tester-only demo. | AC-002/012/015/016/017 | Disable public chat with the kill switch; retain snapshots, turns and published data. |
| P4-05: owner history API | Completed locally and verified; owner-scoped list/detail over durable visitor turns, bounded cursors, safe status projections, private-column exclusion, and snapshot-version history. | AC-002/013/014 | Disable history reads; preserve existing conversation rows. |
| P4-06: owner publishing/history UI and widget | Implemented locally. Publish readiness/conflict/update and snippet; bounded owner history; Vite-hosted loader and isolated iframe; frame-memory-only tester/visitor tokens; exact-origin public-route CORS and same-origin embedding rejection. | AC-010-016/018; NFR-003/004 | Disable owner UI routes and widget entrypoint; keep public chat off; preserve compatible assets and snapshots. |
| P4-07: integrated acceptance and learning | Local acceptance completed: 11 PostgreSQL integration tests and 5 browser tests passed; the full owner-publish -> external widget -> gated chat -> owner-history journey passed locally. See the 2026-10-24 follow-up below. | All Phase 4 ACs; AC-008/009 regression | Keep public chat disabled until deployment configuration and operational gates pass; preserve snapshots and history. |

#### P4-07 final integration verification (2026-10-23)

Verified locally:

- The Phase 1-4 PostgreSQL integration tests passed 39 cases against a disposable local pgvector database. Alembic reached `0006_publication_budget`; read-only checks confirmed forced RLS on the tested application tables and restricted public-runtime grants. No live Supabase database was accessed.
- The full offline backend suite passed 458 tests; 39 opt-in PostgreSQL tests were skipped in that run. Those are separately covered by the 39 passing PostgreSQL tests above.
- Frontend tests: 68 passed. Lint, typecheck, and production build passed.
- Individual cross-origin widget browser scenarios reported successful assertions, but Playwright remained alive after scenario completion and required interruption. The complete browser suite has no clean successful process exit and is not marked passed.
- Vite warned that the minified JavaScript chunk is 580.87 kB (168.24 kB gzip), above its 500 kB warning threshold. Build succeeded; route-level lazy loading is an optional later optimization.
- No live Supabase changes, provider calls, deployment, commit, or push occurred.

Two acceptance gaps remain:

1. Obtain a clean exit from the cross-origin Playwright suite without masking a stuck runner as success.
2. Verify one integrated owner-to-widget-to-history browser flow: owner publishes and copies the snippet; a distinct-origin page embeds it; an authorized tester chats against the published snapshot; the owner sees the conversation in history. Check demo gating and ensure tokens, internal citations, and draft-only data are not exposed to the host.

Readiness as of 2026-10-23: local PostgreSQL/security and frontend/backend regression checks were verified, but Phase 4 was not yet accepted for a controlled two-tester demo. Live deployment readiness was not verified. The two gaps were closed in the 2026-10-24 follow-up below. Shared durable AI-budget dispatch remains deferred and is a mandatory gate before unrestricted public launch.

#### P4-07 acceptance follow-up (2026-10-24)

The two gaps listed in the 2026-10-23 verification were closed locally. The
Playwright widget suite exited cleanly with code 0 (5 tests passed), and the full
owner-publish -> external-origin widget -> gated visitor chat -> owner conversation
history journey passed locally against a disposable PostgreSQL database using mocked
AI providers. Verification included rejected demo access, host-page token privacy,
and private-citation non-disclosure. Eleven PostgreSQL integration tests passed for
the final acceptance run. No live Supabase service, paid AI provider, deployment,
commit, or push was used for this verification.

Local Phase 4 acceptance: **GO**. Live deployment readiness remains unverified;
public chat remains disabled until the separately reviewed deployment configuration
and operational gates pass. Shared durable AI-budget dispatch remains deferred and
mandatory before unrestricted public launch.

Next-session checklist, in priority order:

1. Resolve the Playwright shutdown issue and obtain a clean suite exit.
2. Run the controlled full browser flow above with the server-side gate restricted to the two approved testers; verify owner history and host-visible network data.
3. Review the resulting acceptance evidence, then prepare a separately authorized live-demo deployment review. Leave public access disabled until it passes.
4. Consider route-level lazy loading only if the bundle warning affects delivery; it is not required to close the acceptance gaps.

Rollback must keep configuration and index together. A retained index is usable
only while its embedding provider/model/dimension remains supported; incompatible
rollback fails closed. Public kill switch remains available independently of
publishing. Schema/application/recovery compatibility must be checked before
rolling application code back; an older recovery tool must continue refusing a
new schema. Do not garbage-collect old snapshots in this phase.

Approval and verification gates:

1. Close the two outstanding P4-07 acceptance gaps: clean Playwright suite exit and
   the integrated owner-publish-to-widget-chat-to-history browser journey.
2. Before a controlled live demo, obtain separate explicit approval. Verify the actual
   target database roles/RLS, exact widget/API origins, TLS/CSP, and server-side gate
   for no more than the two authorized testers. Keep public chat disabled until checks
   pass.
3. Shared durable AI-budget dispatch remains deferred for the limited demo and is a
   mandatory gate before unrestricted public launch. Confirm provider pricing and
   operational limits before enabling any live provider path.
4. After acceptance, complete the required Phase 4 learning review and record the
   final human review. Live migration, deployment, and paid provider smoke tests each
   require separate explicit approval.

Security references: [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)
and [MDN CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS).

### Phase 5: Hardening and MVP acceptance (3-4 days)

Status: planned; follows Phase 4 and includes full frontend/backend regression.

Required MVP work:

- Run the full automated acceptance suite and owner-isolation tests.
- Exercise file-processing failures, unavailable response dependencies, malformed embed requests, and publish/update failures.
- Review data exposure, authorization boundaries, input validation, file handling, secrets handling, and logging for sensitive content.
- Perform a small end-to-end validation of creation, configuration, knowledge upload, optional playground use, publishing, embedding, visitor conversation, and history viewing.
- Confirm that excluded features have not entered the MVP: platform-specific integrations, advanced analytics, search, export, sentiment analysis, visitor identification, automated evaluation, or provider/infrastructure commitments.

Tests and traceability: all requirements and AC-001 through AC-018, with particular emphasis on NFR-001 through NFR-004.

## Requirement and acceptance-criterion coverage

| Specification item | Planned implementation and tests |
| --- | --- |
| FR-001; AC-001-002 | Phase 1 owner services and isolation tests; UI/UX sprint browser creation/listing and account-switch tests. |
| FR-002; AC-003 | Phase 1 configuration persistence; UI/UX sprint save/reopen forms, with Phase 2 file associations. |
| FR-003; AC-004-007 | Phase 2 file lifecycle; UI/UX sprint upload/list/download/remove/replace browser tests. |
| FR-004; AC-008-009 | Playground service tests using current draft configuration and knowledge. |
| FR-005; AC-017 | Grounding/fallback orchestration tests, including insufficient-knowledge and failed-retrieval cases. |
| FR-006; AC-010 | Publish tests proving playground use is optional. |
| FR-007-008; AC-011-012 | Embed-snippet generation and published-assistant widget contract tests. |
| FR-009; AC-013-014 | Conversation recording, owner-scoped list, detail, message, and timestamp tests. |
| FR-010; AC-015-016 | Draft/public isolation and publish/update transition tests. |
| NFR-001-002; AC-018 | Workflow contract and UI/API tests showing no model-parameter or code input is required. |
| NFR-003-004; AC-012 | Embed copy/paste contract test and compatible-site integration test boundary. |

## Security and owner-data isolation

- Resolve the current owner before every read and write involving assistants, files, conversations, playground sessions, published versions, and embed access management.
- Enforce ownership in the service/domain layer as well as at the HTTP boundary so alternate endpoints cannot bypass isolation.
- Reject cross-owner identifiers with the same safe not-found or unauthorized behavior chosen during implementation; do not reveal whether another owner's records exist.
- Validate uploaded file type and size according to the approved operational limits when those limits are selected; quarantine failed or untrusted processing results.
- Treat uploaded documents and retrieved text as untrusted content. Prevent them from changing system instructions or crossing assistant ownership boundaries.
- Keep provider credentials, signing material, and operational secrets outside source control and out of assistant-visible content.
- Avoid logging full visitor messages, uploaded contents, or credentials by default; protect any diagnostic data that must be retained.
- Apply request validation, rate controls, and abuse protections appropriate to public visitor chat without adding a separate product feature.

## Failure handling

- Upload failure: mark the file unavailable, report a user-actionable error, and exclude it from retrieval until processing succeeds.
- Unsupported or malformed document: reject it without associating partial content with the assistant.
- Retrieval unavailable or no sufficient relevant knowledge: return the configured fallback message and do not generate a business-specific answer.
- AI response failure or timeout: return a safe failure response consistent with the configured fallback behavior; do not expose provider errors or internal details.
- Draft publish failure: keep the prior published version active and leave the changed version available as a draft for retry.
- Conversation persistence failure: do not claim a conversation was saved when it was not; record an operational error without exposing sensitive content.
- Embed or public request for an unpublished or unavailable assistant: fail safely without exposing draft configuration or owner data.

## Architecture references

The original candidates have been resolved/grouped into the existing accepted ADRs:

- ADR-001: Data Platform, Persistence, and Ownership Isolation.
- ADR-002: Authentication and Authorization.
- ADR-003: Knowledge Storage, Processing, and Semantic RAG.
- ADR-004: AI Generation and Embedding Integration.
- ADR-005: Publishing, Public Widget, and Public Access Security.

Their decisions remain unchanged. The UI/UX sprint proposes frontend build/routing,
browser session storage and origin configuration for review; no new accepted ADR
is created by this planning update.

## Technical risks and assumptions

Risks:

- PDF/DOCX extraction quality may make grounding unreliable, especially for complex layouts or scanned documents.
- Retrieval may return insufficient or misleading context; the fallback boundary must remain conservative.
- Keeping draft and published behavior separate can create stale or partially published state if transitions are not atomic.
- Public embed traffic and visitor history create data-isolation, abuse, and operational-load risks.
- The 4.5-week window leaves little room for advanced document handling, broad compatibility testing, or rework after provider/storage decisions.

Assumptions:

- Supabase Auth and verified FastAPI owner context are implemented under ADR-002; the UI/UX sprint consumes that boundary.
- The project will use Python and FastAPI for the backend boundary as supplied by the request.
- The MVP can use replaceable interfaces for persistence, file storage, retrieval, and AI response generation while concrete technologies are selected.
- The owner-configured fallback message is sufficient for unknown-answer behavior; no automated answer-quality evaluation is required.
- A website that permits JavaScript insertion is the only embedding compatibility boundary required by the specification.

## Optional future work

Not required for this MVP and excluded from implementation phases:

- Advanced analytics, conversation search, export, sentiment analysis, and visitor identification.
- Platform-specific WordPress, Shopify, React, or other integrations.
- Automated answer-quality evaluation.
- Additional document formats beyond PDF and DOCX.
- Provider-specific tuning or model-parameter controls exposed to business owners.

## Rollback note

Release changes in small, reversible increments behind the draft/published boundary. If a release causes incorrect responses, data exposure, failed processing, or broken embedding, disable or revert the affected endpoint/component while keeping the last known-good published assistant version active. Restore persisted data from the approved recovery process if needed, and do not promote a draft version until the relevant acceptance and isolation tests pass again.
