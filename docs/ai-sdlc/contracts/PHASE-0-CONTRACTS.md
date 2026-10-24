# Phase 0 Contracts

Status: draft

This document turns the current SPEC-001 requirements and accepted ADRs into implementation contracts. Later phase refinements include persistence/security designs for review; this document does not implement database objects, framework code, provider SDKs or infrastructure configuration.

## Contract boundaries

### Authentication boundary

- Supabase Auth owns registration, login, and logout.
- Protected FastAPI operations receive an authenticated Supabase user context.
- FastAPI derives `owner_id` from that context; clients cannot choose the owner for an owner-scoped operation.
- Owner-scoped operations must apply both FastAPI owner checks and Supabase RLS.
- Public widget/chat operations do not receive owner credentials and cannot access draft or owner-only data.

### Domain boundaries

- `AssistantService`: assistant creation, owner-scoped configuration, draft state, and publish/update orchestration.
- `KnowledgeService`: file association, limit validation, processing state, and retrieval eligibility.
- `Retriever`: accepts an assistant and query context and returns ranked eligible chunks; it does not generate answers.
- `AnswerGenerator`: accepts approved assistant behavior and retrieved context; provider configuration is deployment-only.
- `ConversationService`: records visitor conversations and exposes owner-scoped history views.
- `PublicAssistantService`: resolves an opaque public identifier to the active published snapshot only.

## Identifier rules

- `owner_id`: the Supabase Auth user UUID. It is server-derived and never accepted as an authority from the request body.
- `assistant_id`: an opaque server-generated UUID. Every owner operation must scope it to the authenticated `owner_id`.
- `knowledge_file_id`: an opaque server-generated UUID scoped through its assistant and owner.
- `conversation_id` and `message_id`: opaque server-generated UUIDs scoped through the assistant and owner relationship.
- `published_snapshot_id`: an opaque server-generated UUID identifying an immutable published snapshot.
- `public_assistant_id`: a separate opaque, non-sequential public identifier used by the JavaScript widget. It must not encode `owner_id`, draft state, or provider information.
- Clients may send resource identifiers to select a resource, but the service must verify ownership before reading or mutating it.
- Cross-owner identifiers must not reveal whether the referenced resource exists.

## Assistant lifecycle and version contract

| Event | Draft state | Active public state | Required result |
| --- | --- | --- | --- |
| Create assistant | New editable draft | None | Assistant is owner-scoped and unpublished. |
| Edit an unpublished assistant | Updated draft | None | Public access remains unavailable. |
| Edit a published assistant | Updated draft | Previous published snapshot | Public behavior remains unchanged. |
| Publish an unpublished assistant | Draft retained as current source | New immutable snapshot becomes active | Activation is atomic. |
| Publish updates | Updated draft retained | New immutable snapshot becomes active; previous snapshot preserved | Public requests switch only after successful activation. |
| Publish failure | Draft retained | Previous active snapshot remains active | No partial public state is exposed. |
| Remove or add knowledge | Draft knowledge association changes | Previous published snapshot remains unchanged | Public retrieval does not see the change until publish/update. |

Additional rules:

- Playground use is optional and never a publish prerequisite.
- A public request resolves only to the active published snapshot.
- A failed publish must leave the prior active snapshot available for recovery.
- A snapshot is immutable after activation; later owner edits create or update draft state.

## Owner API contract inventory

The following operations are contract targets for later implementation. Phase 0 does not implement them.

| Operation | Authentication | Input boundary | Observable success | Required failures |
| --- | --- | --- | --- | --- |
| Register / login / logout | Supabase Auth | Auth-specific credentials/session | Authenticated Supabase user context or logout completion | Invalid credentials/session; no owner data disclosure. |
| Create assistant | Authenticated owner | Assistant configuration fields; no provider/model fields | New owner-scoped draft assistant | Invalid input; unauthenticated request. |
| List/get/update assistants | Authenticated owner | Assistant identifier and editable configuration | Only the owner's assistants and current draft state | Cross-owner or missing identifier behaves as a safe not-found/unauthorized result. |
| Upload knowledge file | Authenticated owner | PDF or DOCX file, at most 10 MB | File metadata with processing state | Unsupported type, over 10 MB, sixth file, malformed/encrypted/scanned/empty processing. |
| List/view/remove knowledge file | Authenticated owner | Assistant/file identifiers | Owner-scoped metadata or removal result | Cross-owner, missing, or not-ready file. |
| Playground message | Authenticated owner | Assistant identifier and user message | Response based on current draft configuration and eligible knowledge | Missing assistant, retrieval/provider failure, or insufficient context uses configured fallback/safe failure. |
| Publish/update assistant | Authenticated owner | Assistant identifier | New active immutable published snapshot and public identifier | Invalid draft, failed processing, or activation failure leaves prior public state unchanged. |
| Get embed snippet | Authenticated owner | Published assistant identifier | Generic JavaScript snippet containing only the opaque public identifier | Unpublished or cross-owner assistant. |
| List conversations | Authenticated owner | Assistant identifier | Conversations for that assistant with owner-visible metadata | Cross-owner or missing assistant. |
| Get conversation | Authenticated owner | Assistant/conversation identifiers | Messages and timestamps for that assistant | Cross-owner or missing conversation. |

Provider base URL, API key, model name, embedding provider, and embedding model are never accepted or returned by these owner APIs.

## Public API contract inventory

| Operation | Authentication | Input boundary | Observable success | Required failures |
| --- | --- | --- | --- | --- |
| Public chat | Opaque public assistant identifier; no owner auth | Public identifier and visitor message | Response from active published snapshot only; conversation recorded when persistence succeeds | Unknown/unpublished identifier, rate limit, provider failure, or insufficient context uses safe fallback/failure. |
| Widget asset delivery | Public widget request | Generic widget request and public identifier | Widget communicates with the FastAPI public chat boundary | Must not expose draft configuration, owner data, provider credentials, or model settings. |

The initial single-instance rate limit is approximately 30 requests per minute per IP/public-assistant pair and remains configurable.

## Phase 4 publishing and visitor contracts (P4-01, 2026-10-23)

Status: P4-01 design documented from explicit conditional approval. Human-approved
MVP decisions are recorded below; no security design choice remains open.
These concrete routes refine the inventory above; they are not existing endpoints. Implementation tasks, security decisions,
tests and rollback gates remain in PLAN-001's Phase 4 section. ADR addenda record
the approved design without changing prior Phase 1/2 decisions.

### Owner operations

All routes use existing Supabase authentication and the owner runtime transaction
boundary. The server derives ownership; bodies reject owner IDs, provider settings
and arbitrary snapshot/index IDs. Cross-owner requests are indistinguishable from
not-found resources. Keep existing assistant configuration APIs unchanged.

| Proposed route | Request | Success | Failure |
| --- | --- | --- | --- |
| GET `/assistants/{id}/publication` | Owner session | `published`, `public_id` (nullable), `version` (nullable), server-generated `draft_fingerprint`, `has_changes`, `readiness` (`ready`, `fallback_only`, `needs_preparation`, `processing`, `failed`) | 401/404; 503 if state cannot be read safely |
| POST `/assistants/{id}/publication` | `expected_draft_fingerprint`, `expected_published_version` (nullable for first publish); `Idempotency-Key` header | 201 snapshot created, or 200 replay; stable `public_id`, new `version`, `published_at`, updated fingerprint | 409 `draft_changed`, `publication_changed`, `knowledge_not_ready`, `idempotency_conflict`; 422 invalid input; 503 publication unavailable |
| GET `/assistants/{id}/embed` | Owner session | Generated `snippet` and `public_id`, targeting configured widget asset origin | 409 `not_published`; 401/404 |
| GET `/assistants/{id}/conversations` | Bounded cursor/limit (proposed default 20, max 100) | `items` with ID and server timestamps, `next_cursor` | 401/404/422 |
| GET `/assistants/{id}/conversations/{conversation_id}` | Bounded message cursor/limit | Ordered messages with role, text, timestamps, outcome/status and next cursor; only this owner's assistant | 401/404/422 |

Fingerprint is an optimistic concurrency token, not authorization. The publisher
recomputes and checks it under locking. Replaying an idempotency key with different
payload returns conflict; replay returns the original result even if later publishes
exist. The UI refreshes publication status rather than treating that replay as current.
If the same committed content is already active, return its existing version rather
than duplicating it. No publication operation invokes embeddings or generation.

Snapshots keep all published behavior and source/index references immutable.
Draft status, Playground behavior and the five-current-file limit stay independent
of publication. A first publish never requires Playground use. Zero-file fallback-only
publication is approved. Processing or failed attachments block publication; all other
current attachments must belong to the matching ready index.

### Public operations

The public router uses a separately reviewed restricted database context, never
`CurrentOwner` with an inferred owner ID. The widget uses no Supabase session/key.
The public assistant identifier is randomly generated, stable across updates and
unrelated to owner/internal assistant identifiers; possession gives only public access.

| Proposed route | Request | Success | Failure |
| --- | --- | --- | --- |
| GET `/widget.js` and `/widget` | Asset request; frame takes public ID | Generic loader/frame assets; no private or provider configuration | Safe unavailable UI if loading fails |
| GET `/public/assistants/{public_id}` | Public ID only | Only published display name, colors and public version number | Uniform 404 `assistant_unavailable` for unknown/unpublished; 429 if rate-limited |
| POST `/public/assistants/{public_id}/conversations` | Empty strict object | 201: opaque `conversation_id`, random `conversation_token`, `expires_at` | 404/429/503; no provider call |
| POST `/public/assistants/{public_id}/conversations/{conversation_id}/messages` | Dedicated visitor-token header; JSON `message`, client-generated `request_id` | 200: `message_id`, `answer`, `outcome` (`grounded`/`fallback`), `created_at`, public `version` | 404 for invalid scope/capability, 409 `request_in_progress`/`request_conflict`/`published_version_changed`, 422 input rejection, 429 rate/budget limit, 503 safe service failure |

Public responses omit raw citation IDs/excerpts/filenames as approved;
citations are still validated internally against the exact
packed published evidence. Do not return owner IDs, index manifests, storage paths,
signed file URLs, prompts, internal exception text, provider names or usage details.
Only safe text and published visual configuration reach the widget. The owner sees
a notice that publishing makes answers based on selected knowledge publicly accessible.

### P4-06 widget hosting and CORS boundary

- The existing React/Vite deployment serves `/widget.js` and the `/widget` iframe
  route. FastAPI does not serve frontend assets. The configured `WIDGET_ASSET_ORIGIN`
  is the exact origin used by the embed snippet and iframe.
- FastAPI adds CORS only to `/public/assistants/{public_id}` routes. The allowed
  origin must exactly equal `WIDGET_ASSET_ORIGIN`; wildcard origins and credentials
  are not allowed. Preflight permits GET/POST and only `Content-Type`,
  `X-Demo-Access`, and `X-Visitor-Token`. Owner endpoints do not receive widget CORS.
- With public chat disabled, the iframe displays an unavailable state. When enabled
  for the approved demo, a tester types the demo access code into the frame. It is
  held only in JavaScript memory and sent in `X-Demo-Access`, never in the snippet,
  query string, local/session storage, or parent page. The returned visitor token
  is likewise memory-only and sent in `X-Visitor-Token`.
- A browser integration test embeds the loader from an origin different from the
  iframe host, and verifies that no token or chat content is passed to the host
  page. The only iframe-to-host message is a fixed close notification.
  The loader refuses same-origin embedding because a same-origin host could inspect
  the iframe DOM despite sandboxing; production widget hosts must use a distinct
  origin from the configured widget asset origin.

P4-06 implementation status: local owner publishing and conversation history
screens, static loader, `/widget` iframe UI, and exact-origin public-route CORS are
implemented. The browser test uses a distinct host origin and controlled HTTP
responses; this does not enable public chat or verify deployment proxy/CORS settings.

Local verification (2026-10-23): backend full suite passed 458 tests; 39
PostgreSQL-gated tests were skipped because no disposable integration configuration
was enabled. Frontend unit tests passed 68 tests across 7 files; lint, TypeScript,
and production build passed. Playwright reported the individual P4-06 scenarios as
`ok`, but its process did not exit after the scenarios completed and had to be
interrupted; treat browser-suite process completion as unresolved. No live Supabase,
provider, deployment, or public-chat verification was performed. The build reports
the existing-size warning for the generated JavaScript bundle.

Store only a hash of the high-entropy conversation capability. Bind it to its
conversation and public assistant; validate before reads/writes and pass only
server-derived context to the repository. Keep it in frame memory, send it in a
redacted header, and never log it or put it in a query string/snippet. TTL is 24 hours
from creation using database UTC time, with no sliding renewal. Expiry ends visitor
access, not owner history retention. Losing the token starts a new conversation;
there is no visitor history-list/read endpoint. Owner history does not return tokens.
No visitor identity, fingerprinting, cross-site tracking, or third-party cookies.

Use independent model turns, with visual/persisted grouping only. Each turn
resolves the active published snapshot afresh, pins it across retrieval/generation,
and rechecks under a mapping lock before final persistence. A version change discards
the generated reply with safe conflict; no automatic retry or mixed-version answer.

### Public request safety and failure contracts

- Validate JSON body size and UTF-8 question size before embedding. Preserve current
  adapter limits: at most 1,000 question bytes, 3,000 evidence bytes, 6,000 assembled
  prompt budget including the 512 framing reserve, at most five chunks, and existing
  output bounds. These conservative byte guards must not be confused with the older
  proposed token limits elsewhere in this document. Exceeding them does not cause
  truncation or a relaxed limit. Configure a bounded total HTTP body separately.
- Check service-enabled, IP/assistant rate, global concurrency and persistent daily
  cost reservation before paid work. Reuse the configurable ADR-005 30 RPM boundary;
  initial caps are $0.01/message, $0.10/index and $1/day, conditional on verified
  provider pricing. The shared accounting privilege mechanism below requires review.
- An empty published knowledge set returns its exact fallback locally. With indexed
  knowledge, no relevant matches returns fallback with no generation call; query
  embedding may already have been billed. Provider failure is 503, not insufficient
  knowledge. Never leak detailed provider codes to visitors.
- Request IDs are unique per conversation. Store a durable pending turn before AI
  I/O; replay of completed identical input returns the saved reply without new calls.
  Conflicting content is 409. Pending/uncertain attempts never trigger duplicate AI
  work automatically. A worker crash retains reservation and uncertainty until
  operator reconciliation; a manual new turn is a separately budgeted request.
- Commit successful answer/fallback, timestamps and completion status before returning
  success. If initial persistence fails, do not call providers; if completion persistence
  fails after a call, return safe failure, retain uncertain cost and do not claim a
  saved answer. Owner history may show the attempted user turn with failure/pending
  status but must not display internal errors as assistant answers.
- Conversation grouping does not pin future turns to old snapshots. New turns after
  publish use the new active version. Old records retain their original version.
- Use no-store for mutable public configuration, tokens and chat responses. Static
  versioned widget assets may be cached; deployment must preserve asset compatibility.
- No cross-origin owner credentials; separate public and owner route policies. CORS
  controls browser reads, not authorization or protection against direct HTTP bots.
  No required per-owner domain setup or new domain-management feature for the MVP.
- Recovery preserves every retained published source/index reference, including
  inactive rollback versions. Reference creation and cleanup claims must serialize;
  publication refuses missing/claimed artifacts. Extend the exact recovery baseline
  with explicit reviewed objects; retain fail-closed behavior for unexpected schema.

### P4-01 exact security design (design only; no grants applied)

This subsection supersedes unresolved recommendations in the original Phase 4
proposal. Separate public runtime, durable shared
reservations, conditional numerical budgets, fallback-only publication, blocking
processing/failed attachments, 24-hour capabilities, independent turns, no public
source metadata, isolated iframe and version-change rejection are approved.
The detailed role/function mechanism below is a design for review before P4-02.
Object names below are proposed migration contracts, not claims of existing tables.

#### Runtime and policy matrix

`assistant_runtime` remains the verified-owner login. Add
`assistant_public_runtime` through a separate `PUBLIC_DATABASE_URL`, with no fallback
to owner/migration credentials. Both are LOGIN, NOSUPERUSER, NOBYPASSRLS, NOCREATEDB,
NOCREATEROLE, NOREPLICATION, NOINHERIT, own no tables/functions and have no privileged
role memberships. Grant CONNECT to the application database and USAGE on the
required schemas, never CREATE. Migration credentials remain operator-only.
No new runtime DELETE, TRUNCATE, REFERENCES, TRIGGER or schema-wide grants.
UUID keys require no sequence grants. Existing owner permissions remain unchanged.

All new application tables have ENABLE/FORCE RLS and explicit role-specific policies.
No grants to PUBLIC, anon, authenticated, or service_role on the new objects, including
column/default/function grants; inspect inherited privileges too. Do not revoke
unrelated Supabase privileges or change Auth. The private accounting schema must
not be exposed through PostgREST. Public HTTP access is through FastAPI only.

Define policy predicates:

- **O(row):** `row.owner_id` equals validated transaction-local `app.owner_id`.
- **P(mapping):** mapping public ID equals transaction-local `app.public_id` and
  has a non-null active snapshot. Resolution starts with this public ID only.
- **S(snapshot):** a P-visible mapping points to that exact snapshot, with matching
  owner/assistant keys; snapshot ID equals server-pinned `app.snapshot_id`.
- **R(ref):** its snapshot satisfies S; its index/file/owner/assistant composite
  keys match the immutable published source manifest.
- **C(conversation):** its public mapping satisfies P, conversation ID equals
  `app.conversation_id`, stored token digest equals `app.visitor_token_digest`, and
  `expires_at > transaction_timestamp()`. C does not require the snapshot at
  conversation creation to remain active; new turns resolve the current snapshot.
- **T(turn):** its conversation satisfies C. New turns must also reference S;
  completion requires the same S as when the turn began.

Context parsers return no match for absent/empty/malformed values; never substitute
an owner or default ID. Set transaction-local values before queries and test reuse
after commit/rollback. The raw token is hashed before DB access; digest is sensitive
too and excluded from SQL-parameter logging. Supabase verifies owner authentication;
the public token grants only one conversation. Public ID alone grants no history.

| Object | Owner runtime grants and policy | Public runtime grants and policy |
| --- | --- | --- |
| Existing assistants/files/text/indexes/sources/batches | Existing owner policies/grants unchanged | None |
| `assistant_publications` | SELECT, INSERT; UPDATE only `active_snapshot_id`, `updated_at`; O on reads and both write predicates | SELECT only `public_id`, `owner_id`, `assistant_id`, `active_snapshot_id`; P |
| `published_snapshots` | SELECT, INSERT; O; no UPDATE/DELETE | SELECT only identity keys, version, published configuration/fallback, embedding-space/retrieval configuration; S |
| `published_sources` | SELECT, INSERT; O; no UPDATE/DELETE | SELECT only snapshot/index/file/owner/assistant keys; R; no frozen filenames |
| Existing `knowledge_chunks` | Existing owner grants unchanged | SELECT only identity keys, ordinal, offsets, extraction version, chunk text and embedding; EXISTS an R-visible matching source; no INSERT/UPDATE |
| `publication_requests` | SELECT, INSERT with O; immutable key/fingerprint/result association | None |
| `visitor_conversations` | SELECT history columns only with O; exclude token digest | SELECT identity/public mapping keys and expiry only, C; INSERT explicit identity/mapping/digest/created/expiry columns, P plus context ID/digest; no UPDATE |
| `visitor_turns` | SELECT history columns only with O; no writes | SELECT scoped turn fields, T; INSERT request ID, input digest, user text, snapshot keys, pending state and timestamps with T and S; UPDATE only state, answer, outcome, completed timestamp and safe error code with T and final S |
| Accounting tables | No direct privileges | No direct privileges |

RLS policy dependencies are one-way: mapping -> snapshot -> source -> chunk;
mapping -> conversation -> turn. No recursive policy joins to drafts or indexes.
Conversation policy may inspect its digest without granting the runtime permission
to select the digest column. Server-populated owner IDs for public INSERTs come from
P, never request input; composite foreign keys and WITH CHECK require matching P.
The owner-column projection on public mappings is internal DB data, never HTTP data.
Policies distinguish SELECT/INSERT/UPDATE; every UPDATE has USING and WITH CHECK.
Owner policies cannot accidentally OR-open public access: roles have no membership
in each other and public code never uses the owner engine.

Database constraints/guard triggers additionally enforce immutable identity columns,
non-null/default server timestamps, 24-hour expiry, pending-only turn INSERT,
one-way terminal turn transitions, immutable completed replies, unique
conversation/request ID, and composite ownership/snapshot references. They must
reject direct invalid SQL, not rely only on Python. Failed/version-rejected turn
finalization may change status/error only after a version switch; it cannot store
an answer. This needs a separate UPDATE policy branch for that terminal failure,
without S, but still with T and an immutable pinned snapshot.

Application trust limitation: transaction settings are assertions by trusted
FastAPI, not cryptographic SQL identities. A compromised public DB credential can
forge public context and access published evidence; it must still be denied all
drafts and originals. Forging a valid conversation requires its unpredictable token
digest. Arbitrary application-code execution compromises both configured engines;
two roles in one process do not create process isolation. No RLS claim exceeds this.

#### Shared budget boundary — conditionally approved security design

Recommend `ai_accounting` (unexposed schema) with global UTC-day buckets, operation
envelopes and provider-attempt reservations. Store opaque operation IDs, caller
role, scope digest, kind, price version, integer micro-USD ceilings/charges, usage
counts, timestamps and state only. No prompts, answers, filenames, tokens, owner
profile data or embedding vectors. No tenant table is made globally readable.

Add a **NOLOGIN, NOBYPASSRLS** `assistant_budget_executor` role, not owned/assumable
by either runtime, not an application-table owner. It has schema USAGE and only
SELECT/INSERT plus required counter/state UPDATE columns on accounting tables.
Accounting tables are migration-owned and forced-RLS; policies permit only this
executor to operate across accounting rows. It has no tenant-table privileges.
For each accounting table, its policy targets only `assistant_budget_executor`;
SELECT uses `USING (true)`, INSERT uses `WITH CHECK (true)`, and UPDATE uses both
`USING (true)` and `WITH CHECK (true)` for the narrow granted columns. No DELETE
policy/grant exists. The cross-operation accounting policy is intentional, not a
public/owner policy. RLS applies to the executor's SECURITY DEFINER statements;
runtime login roles do not inherit its table privileges.

Expose only fixed-signature SECURITY DEFINER functions owned by that executor:

- `reserve_attempt(operation_id UUID, attempt_id UUID, kind TEXT, scope_digest TEXT,
  price_version UUID, max_input_tokens BIGINT, max_output_tokens BIGINT,
  request_fingerprint TEXT)`: validates allowed kind/caller, nonnegative bounded
  token counts and immutable operation identity; computes cost internally and
  returns reservation ID/state or denial. Public login can use public-message kind
  only; owner login can use indexing/Playground only. The function recomputes scope
  from transaction-local owner/assistant context or public/conversation/token-digest
  context, compares it with `scope_digest`, then stores the recomputed digest. The
  argument is never authorization by itself. Fingerprint is a digest, not text.
- `mark_dispatched(attempt_id UUID)`: compare-and-set reserved to dispatched once;
  checks caller/scope, enabled price version, deadline and covered day budgets.
- `settle_attempt(attempt_id UUID, input_tokens BIGINT, output_tokens BIGINT)`:
  compute cost from stored price version, enforce valid counts and caller/scope;
  idempotent identical settlement, conflict for changed usage. Unknown usage is not
  zero and must not call this function with fabricated counts.
- `cancel_undispatched(attempt_id UUID)`: releases only reserved, never dispatched,
  caller-bound attempts. No general refund/reset API.

Day buckets permit executor UPDATE only on held/charged micro-USD counters;
operations only on held/charged totals and state; attempts only on state, dispatch/
settlement timestamps, validated usage and charged amount. IDs, scope, kind, price
version, fingerprints and initial reservation bound cannot be updated. Price/limit
records are SELECT-only to the executor. Cross-day hold records are immutable
allocations whose release is accounted transactionally, never deleted at runtime.
All function state changes and counter deltas are one transaction, with nonnegative
CHECK constraints. Only migration/operator credentials can create price versions.
Revoke default PUBLIC EXECUTE in the same migration transaction, then grant EXECUTE
only to the two runtime logins. Fix search_path to pg_catalog with all application
objects schema-qualified; no dynamic SQL, caller-selected table/role names, default
argument overloads or writable-schema resolution. Validate `session_user` against
the two actual login roles (not `current_user`, which is the executor in the function),
and bind each reservation to caller role and a validated transaction scope digest.
Validate owner context for indexing/Playground and visitor context for public chat;
these are trusted FastAPI assertions, not SQL-side Supabase JWT verification.
Do not make the executor an admin, table owner or RLS bypass role.

Only a migration/operator-managed price/limit record supplies allowed model identity,
unit prices and ceilings. Runtimes cannot change prices, caps or manufacture negative
charges. Functions return reservation outcome/ID, not cross-owner reservation lists.
Caller usage is trusted adapter-observed usage: this boundary prevents accidental
races/direct counter manipulation, not malicious application falsification of bills.
This narrowly privileged function design is conditionally approved for P4-02 design;
it does not grant general SECURITY DEFINER access to tenant data. Applying any
migration still requires separate execution authorization.

Reservation rules:

1. Reserve before every provider dispatch, commit reservation separately from domain
   work, and fail closed on unknown/unverified model pricing or unavailable ledger.
   Index batches share a lifetime $0.10 operation envelope. Query embedding and
   generation share a $0.01 message envelope. All three callers share $1/UTC day.
   Caps are initial policy values conditional on pricing verification, not verified
   invoice estimates. A free candidate also needs verified quota/availability.
2. Lock global day buckets in date order, then operation, then attempt. Atomically
   require charged plus outstanding reservations plus new upper bound <= every
   applicable cap. Integer micro-USD arithmetic rounds costs up. Unique
   operation/attempt keys prevent double reservation or duplicate dispatch claims.
3. The upper bound uses verified billable input and maximum output/reasoning pricing,
   not just visible answer tokens. Adapter guards still apply. No caller can dispatch
   more inputs/output than reserved. Unknown charging semantics block enablement.
4. Mark dispatched durably before sending. No DB transaction spans HTTP. Settle once
   against validated usage, releasing only proven surplus. Missing usage, timeout,
   crash or uncertain send retains the full reservation; lease expiry does not refund
   or automatically retry. Only never-dispatched attempts can be canceled automatically.
   Unexpected cost above reserve trips the AI kill switch and needs operator review.
5. A reservation may not cross midnight unaccounted. Before dispatch, atomically
   cover every UTC day touched by the bounded request deadline (normally current
   day, at most next day). Hold that bound on each covered day; conservatively keep
   settled/uncertain cost on both for crossing calls. Do not release an old-day hold
   to create new-day credit for an in-flight request. This deliberately overcounts
   rather than promising precise provider billing-day alignment.
6. Recovery never edits a global balance directly. An operator reconciliation path
   is separate from runtime HTTP, audits reservation IDs/reasons without content and
   requires evidence before release. Crash between reservation and domain update
   can waste budget but cannot grant free calls. All existing indexing/Playground
   dispatches must adopt this boundary before public enablement; old provider paths
   and validation scripts must not run alongside it as unaccounted production work.

Provider-side project caps supplement this estimate; external use of the same key,
price changes and provider charging rules prevent an application ledger from being
an absolute billing guarantee. No price verification or provider call occurred here.

#### Publication, cleanup and concurrency invariants

- Snapshot includes frozen behavior/name/colors/fallback, calibrated retrieval policy,
  embedding identity, complete source/index manifest and version. Secrets remain
  deployment settings. No snapshot/source UPDATE/DELETE grants; inserts are part of
  one publish transaction and constraints reject cross-owner/assistant references.
  A sealing guard validates complete references at activation and prohibits further
  source INSERTs into any snapshot that has ever activated, not just the current one.
  No partially assembled snapshot may be externally visible or committed as active.
- Publish checks expected fingerprint/version under the existing assistant-row lock,
  then locks publication row, then source files in UUID order. Draft attachment,
  index activation and cleanup claims must respect the same parent-first order.
  Compute the fingerprint from saved configuration plus exact current file/extraction/
  ready-index identity; no client-supplied index. Snapshot, references, idempotency
  result and active pointer commit together. Zero files -> null index + local fallback;
  any processing/failed attachment -> conflict, never partial knowledge publication.
- Public finalization uses a transaction-level advisory lock derived from internal
  assistant UUID; publisher obtains the same lock before pointer change. Public code
  needs no UPDATE privilege on publication just to lock it. After lock acquisition,
  re-read active pointer and token expiry before persisting response. Do not hold this
  lock across provider calls. Publishers take advisory lock before parent-row locks;
  finalizers take advisory lock before turn-row locks. Hash collision only serializes
  unrelated assistants, never authorizes them. All pointer-changing paths, including
  operator rollback, follow this protocol. An HTTP reply may arrive after a later
  publish; the guarantee is the atomic finalization point, not network delivery time.
- A version change yields 409 and records a version-rejected attempt without the
  generated answer. Cost still settles; no automatic AI retry. Token expiry during
  a call yields uniform 404 and no answer; attempted history remains pending for
  operator reconciliation if runtime RLS no longer permits finalization.
- Retained inactive snapshots protect files, extracted text, indexes and chunks too.
  Cleanup claims lock the parent/files and recheck all retained references before
  any external deletion. Publish rejects cleanup-claimed/missing artifacts. Extend
  recovery's exact schema baseline and reference checks together; old tools continue
  failing closed. No snapshot garbage collection in this phase.
- Public replay requires valid unexpired capability and same request-body digest.
  A completed turn from an older public version returns 409 rather than leaking an
  obsolete answer through replay. Owner history retains that original answer/version.
  Same-version replay returns the committed response; pending/uncertain is 409.

#### API and browser refinements

The route tables above are the P4-01 contract. Publish responses also include `version`
for already-active identical content (200). Conversation creation and message endpoints
use `X-Visitor-Token` for subsequent requests, never owner Authorization headers.
Request IDs are UUIDs, idempotency keys bounded to 128 ASCII characters, unknown JSON
fields rejected. History default/max limits are 20/100 with stable timestamp+UUID
cursors. A history turn projects user/assistant messages with timestamps; failed
turns show user input and safe status, never fabricated assistant output.

Serve loader and iframe from the application public asset origin, no separate service.
Allow framing only for the widget route; never relax owner-app framing headers.
The loader creates the isolated frame; tokens and chat text never cross postMessage.
Only bounded resize/open/close messages are accepted after source/origin validation.
Widget HTTP stays same-origin to its API where deployed; any development CORS list
is explicit, with no credentialed wildcard. Render plain text, validate colors,
support keyboard/mobile/RTL, no HTML injection, automatic AI retries or silent token
renewal. Expired conversation offers an explicit new conversation action.

Initial operational guard proposal: 16 KiB JSON body maximum, existing 1,000-byte
question guard, 30 requests/minute/IP/public-assistant shared across public dynamic
routes, at most one in-flight AI turn/conversation, two/assistant and four/global.
These concurrency slots cover indexing and Playground too to prevent competing
provider overload. Reject with 429 before provider dispatch; bound limiter storage,
expire inactive keys, reject new keys at capacity rather than evicting active limits.
One process/worker; trusted proxy addresses explicitly configured, otherwise use
socket peer. A 30-second whole-turn deadline includes DB/embedding/generation and
uses remaining time with existing provider ceilings, never two unconstrained waits.
Numerical operational guard values require load/hosting verification before enabling
public chat; durable cost controls remain effective across process restarts.

#### Acceptance evidence and approval gates

| Test group required in later tasks | Observable assertion | SPEC traceability |
| --- | --- | --- |
| P4-C01 publishing | No Playground use; zero-file fallback publishes; processing/failed blocks; concurrent edits/publishes conflict without partial activation | AC-010/015/016/018 |
| P4-C02 snapshot retention | Draft remove/reindex/config edit does not alter public results; cleanup cannot claim referenced sources; rollback preserves exact knowledge/config | AC-006/007/015/016 |
| P4-C03 actual DB roles | Public login cannot read drafts/text/files or write indexes/snapshots; absent/invalid scope denied; owner A cannot read B history; grants/connection reuse tested | AC-002/013/014/015 |
| P4-C04 capability and history | 24-hour expiry, wrong conversation/token, tokenless access fail; timestamps and owner history retained; pending/completed/replay/version-change behavior | AC-012/013/014/016 |
| P4-C05 cost and faults | Mixed indexing/Playground/public reservations race at cap; exact-boundary/UTC rollover/duplicate settlement/crash/unknown billing all fail closed; no forbidden provider dispatch | AC-008/012/017 safety support |
| P4-C06 responses | Exact fallback with zero knowledge/no matches; no generation without evidence; provider error not fallback; raw citations/filenames/excerpts absent from public payload | AC-012/015/016/017 |
| P4-C07 widget | Separate-origin host, no owner session, copied snippet works, iframe origin/source checks, plain text, expired session, RTL/mobile and no model controls | AC-011/012/018; NFR-003/004 |

These are planned tests, not executed evidence. Security tests require real PostgreSQL
under both runtime logins; skipped tests cannot close the release gate. Mocked provider
tests prove guards, not answer quality. Source disclosure restriction refers to raw
metadata/excerpts in payloads; grounded answer prose necessarily conveys published
knowledge and cannot guarantee that the model never mentions a source name.

The human conditionally approved this narrow function-owner design and its safeguards;
the final matrix is now recorded in ADR addenda. No security architecture choice
remains unresolved for P4-01. P4-02 implementation requires its own authorization.
Provider price/quota verification, deployment origins/proxy chain, real role tests and
request-deadline feasibility remain implementation or enablement gates, not reasons
to invent values or modify live settings. No implementation phase is complete, so no
learning report is asserted by P4-01.

Security references: [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
and [function security](https://www.postgresql.org/docs/current/sql-createfunction.html).
Policies filter rows in addition to privileges; function execution identity and a
fixed safe search path require explicit treatment. This design never relies on
FORCE RLS to constrain a superuser or BYPASSRLS credential.

## Knowledge processing contract

- Accepted input extensions are PDF and DOCX only.
- An assistant may have no more than five knowledge files.
- Each file is at most 10 MB.
- Original files remain private in Supabase Storage.
- Metadata and processing state remain in Supabase PostgreSQL.
- Phase 2 ingestion distinguishes accepted, processing, extracted, and failed.
- `extracted` means text persisted, not ready for retrieval. A later indexing
  contract must establish retrieval readiness; only successfully indexed eligible
  files may contribute chunks. The existing `ready` fixture represents that future state.
- Malformed, encrypted, scanned, empty, and unsupported documents become failed and never become retrievable knowledge.
- Owner file access uses short-lived signed URLs only after authentication and ownership checks.

## Retrieval and generation contract

- `Retriever` returns at most the top five semantic matches for the requested assistant and query.
- Each result is already filtered by assistant/file ownership metadata.
- The minimum similarity threshold is configurable and calibrated with known-answer and unknown-answer fixtures.
- If no result passes the relevance boundary, the response path returns the configured fallback and does not generate a business-specific answer.
- `AnswerGenerator` receives only the approved assistant behavior and retrieved context needed for the response.
- The OpenAI-compatible provider base URL, API key, and model name come from deployment environment configuration and remain outside the product API.
- Embedding provider/model selection is separate from generation-provider selection.
- Track embedding provider/model, vector dimension, and embedding/index version for indexed knowledge.
- Never mix vectors from incompatible embedding models or dimensions in the same active retrieval space.
- When the embedding model changes, regenerate the affected knowledge corpus into a new controlled index/version.
- Do not partially replace the active retrieval space during reindexing.
- Activate the new index/version only after reindexing succeeds and validation passes.
- Preserve a safe rollback path to the previous valid index/version where practical.
- Reindex implementation details may be finalized when knowledge indexing is implemented.

## Error and isolation contract

- Every protected read/write is owner-scoped before data access or mutation.
- Failed processing never creates retrievable chunks.
- Failed publish never changes the active public snapshot.
- Provider errors and internal details are not returned to owners or visitors.
- Public requests never return drafts, owner-only data, credentials, or provider configuration.
- The fallback message is the only business response when relevant context is insufficient.

## Phase 3 Task 1 refinement (2026-10-20)

Status: proposed contracts for human review; approved foundations are distinguished
from recommendations below. No routes, providers, vector tables or RAG execution
are implemented by this task. SPEC/PLAN remain draft. UI-06 live smoke verification
remains pending; provider smoke testing cannot close that gate.

### Approved foundations

Reuse Phase 2 extracted text and immutable file identity. Keep separate
`EmbeddingProvider`, `Retriever`, and `AnswerGenerator` boundaries. Use exact cosine
retrieval, versioned indexes, atomic activation, forced RLS and assistant/owner
checks. Playground turns are independent, use current saved draft configuration,
and return server-validated file/chunk citations without invented page numbers.
No provider/model fields belong in owner APIs.

### Indexing trigger comparison and recommendation

| Candidate | Benefit | Limitation |
| --- | --- | --- |
| Index inside a message request | Fewest routes | Unpredictable first-answer latency, ambiguous retry cost, competes with generation deadline |
| Explicit preparation, bounded batch per request | Durable progress, separate deadlines, resumable without a worker/queue | Additional endpoint and UI readiness/polling flow |

Recommend explicit preparation. Each POST does at most one embedding batch,
persists progress, then returns. A 202 means further preparation requests are
needed, NOT that a durable background worker is running. GET never starts work.
The UI may drive the sequence while open; closing it pauses between requests.
Operator recovery handles expired leases/uncertain provider attempts.

Render's [runtime guidance](https://render.com/tutorials/when-deploys-go-wrong/runtime-errors)
discusses application-server timeouts and recommends offloading long synchronous
work; [workers](https://render.com/docs/background-workers) are a separate service.
Do not invent a universal Render request timeout. Proposed application deadlines
below must be verified against the actual Render plan, proxy, server and client
settings before deployment. No Redis, queue, worker or Render resource is approved
or installed here. If bounded batches do not fit, stop for architecture review.

### Proposed owner HTTP contracts

All routes require verified Supabase owner identity before data access. Wrong-owner
and nonexistent IDs return the same 404. Responses are `Cache-Control: no-store`.
UUIDs below are server-issued resource identifiers, not authority.

| Route | Request | Success |
| --- | --- | --- |
| GET `/assistants/{id}/playground/status` | No body | 200 readiness, preparation operation ID if any, completed/total chunks, safe reason |
| POST `/assistants/{id}/playground/prepare` | `{}` initially, or `{"operation_id":"uuid"}` to continue; required UUID `Idempotency-Key` header per batch | 200 ready; 202 preparing with operation ID, progress and `next_action: continue` |
| POST `/assistants/{id}/playground/messages` | `{"message":"nonblank text"}` only | 200 `{"answer":"text","outcome":"grounded|fallback","citations":[]}` |

Reject extra body fields, including owner_id, history, model, prompt, index_id,
temperature and provider URLs (422). No streaming or persistent chat history.
Status exposes no embedding models, provider names, internal errors or credentials.

Each citation is `{file_id: UUID, chunk_id: UUID, filename: string, excerpt: string}`.
At most five unique citations. Server resolves IDs against the exact retrieved
context, checks owner/assistant/current attachment, and obtains filename/excerpt
from stored data; never trust provider-generated metadata. No signed URLs, page
numbers or storage keys. Unsupported IDs or malformed generation cause a safe
failure, never an answer with fabricated citations. Citation validity does not
prove semantic support: test grounding separately. Render answers as text, not HTML.

| Outcome | HTTP / behavior |
| --- | --- |
| Unauthenticated / missing or wrong-owner assistant | 401 / 404; no provider call |
| Invalid or excessive message | 422; no provider call |
| No usable knowledge, or no matches above boundary | 200 fallback; answer exactly current fallback, citations empty; no generation call |
| Known current source still extracting, stale index, pending reindex | 409 `knowledge_not_ready`; prepare/refresh instruction, no generation |
| Preparation already leased | 409 `preparation_busy`; do not create duplicate operation |
| Configuration or source membership changes during answer | 409 `draft_changed`; discard answer/citations, retry explicitly |
| Input exceeds proposed indexing budget | 409 `index_resource_limit`; ingestion/download remain valid; no silent truncation |
| Local rate/concurrency/cost budget exceeded | 429 `budget_exceeded`; no provider call; Retry-After when known |
| Provider/DB unavailable, timeout, invalid vectors, invalid output | 503 safe error; after ownership/config is known include `fallback_message` exactly as configured, never a fabricated answer |

Errors use `{"detail":{"code":"stable_code","message":"safe instruction"}}`,
optionally `fallback_message` for owned requests with safely resolved configuration.
If authentication/database access fails before configuration is read, do not invent
a fallback. Infrastructure failures remain distinguishable from a valid unknown answer.

### State, freshness, retries and recovery

Index lifecycle: `building -> ready`; `building -> failed|superseded`.
Ready indexes are immutable. A separate atomic assistant active-index reference
selects the current ready version; older valid versions remain for rollback.
Readiness is derived: `no_knowledge|needs_preparation|preparing|ready|failed|blocked`.
Failed extraction alone contributes no context; pending extraction blocks readiness.
No attached eligible text with no pending extraction gives `no_knowledge`.

The manifest includes owner, assistant, sorted eligible file IDs, text/content hashes,
extraction/chunker versions and embedding-space fingerprint. Failed/removed files
are excluded. Configuration is read freshly per message and does not cause reindex.
Capture configuration values and source manifest, then recheck before delivering;
newly committed changes win on the next request. A removal observed before final
authorization invalidates the answer. An already-delivered answer cannot be recalled.

Preparation reserves under a short assistant-row lock; only one live preparation
lease per assistant. Persist operation UUID, batch ordinal, attempt/idempotency key,
deadline and expected manifest before external work. Release SQL transactions for
provider I/O. Commit batch output only with matching unexpired operation token,
expected source manifest, valid dimensions/counts and finite nonzero vectors.
Validate the full corpus and atomically activate only after every chunk succeeds.
Never partially activate or use stale removed-file content while rebuilding.

Completed batch idempotency keys replay recorded results without a new provider call.
Concurrent callers cannot claim the same batch. Persist uncertain attempts and charge
their reserved budget: a timeout may still be billable. No automatic provider retries.
After lease expiry, owner-scoped operator recovery fences the old attempt before
explicit retry; a late response cannot commit. Resume only compatible, validated
completed batches. A model/chunker/manifest change creates a new version.
Do not allow resuming a foreign operation ID or arbitrary storage key.

Reindex failure preserves the previous active reference. It may serve only when it
still matches the current source manifest and the query embedder matches its recorded
embedding space; otherwise report not-ready. A new model cannot query old vectors.
No simultaneous multi-provider routing. Rollback restores compatible deployment
configuration and index reference together, after current attachment checks.

### Proposed resource and cost defaults — approval required

These are deployment guardrails, not new product upload limits. Never silently
discard text. Existing 5-file / 10,000,000-byte rules remain unchanged.

| Resource | Proposed bound |
| --- | --- |
| Chunking | Approximately 600 tokens, 100 overlap; model-compatible tokenizer; preserve offsets |
| Index corpus | 100,000 source tokens and 200 chunks per assistant version; count before provider work |
| Embedding batch | At most 8 chunks / 4,800 input tokens; lower to provider's validated limit |
| Message | 4,000 Unicode characters and 1,000 model tokens; reject if either exceeded |
| Generation | At most 5 chunks / 3,000 evidence tokens; total input 6,000 tokens; output 512 tokens |
| Citation | At most 600 characters of exact source excerpt |
| Provider call | 3-second connect, 12-second total wall-clock; no automatic retries |
| Prepare/message request | 20 / 25 seconds total; query embedding + generation share deadline |
| DB waits / lease | 2-second lock, 5-second statement deadline; 60-second renewable-per-batch lease |
| Concurrency | One preparation per assistant; two provider calls globally on single instance |
| HTTP rate | Per authenticated owner: 6 prepare and 10 message requests/minute; configurable |
| Monetary ceilings | USD 0.10 per index, USD 0.01 per message including query embedding, USD 1/day for Phase 3 AI traffic |

Price configuration must come from the selected provider's verified billing terms;
unknown pricing means paid calls disabled, not assumed free. Reserve conservative
worst-case cost atomically before dispatch, including output tokens and uncertain
attempts; reconcile only with trustworthy usage. A provider-side hard spending cap
is required where available; application estimates alone cannot guarantee an invoice
ceiling. Persist budget reservations/usage and retry accounting across restarts
(minimal usage ledger included in migration design); never log prompt content.
Lower limits to actual provider capacity. Any raised budgets require review.
Actual Render request budgets must exceed application deadlines with margin, or
application budgets must be lowered. Do not solve timeout failures by unbounded retries.

### Provider configuration and validation gate

Generation: `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`.
Embeddings: separate `EMBEDDING_BASE_URL`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`,
and validated `EMBEDDING_DIMENSION`. Also configure tokenizer/version, threshold,
limits and verified prices. Secrets server-only with redacted representations.
Never derive the embedding provider from generation configuration automatically.
Require HTTPS approved endpoints; disable credential-bearing cross-host redirects.

2026-10-20 check: all six endpoint/key/model variables absent in both the process
environment and backend/.env. Values were not printed. No provider request was
made; no endpoint, model, dimensions, latency, quota or cost has been validated.
Provider-specific data-processing approval is not established. Previously suggested
model names are candidates only, not selections.

Before any live smoke test: approve the named provider/endpoint and synthetic-only
processing, securely configure credentials, verify model catalog and account quota,
terms/retention and price ceiling. Use this task's synthetic corpus only. Limit the
smoke test to one document embedding batch, one query embedding batch and four chat
calls, at most USD 0.05 total, no retries; stop on any invalid/auth/quota response.
Record vector count/dimension/finite norms, compatible API behavior, grounded Arabic/
English results, latency, reported usage and safe timeout classification.
Live success does not validate full quotas; dashboard/terms verification remains
separate evidence. Keep dimension, model names and numeric relevance threshold
unresolved until evidence exists. Extend held-out fixtures before calibration;
this small corpus is not a statistically representative evaluation platform.

### Migration compatibility plan (later task, no migration here)

Add version/manifest metadata, immutable owned chunks, atomic active reference,
and minimal budget-attempt ledger through an additive migration. Composite foreign
keys and forced RLS must preserve owner/assistant/file/index identity; runtime
cannot update ownership, bypass RLS or use migration credentials. Validate vector
dimensions against the version metadata. Exact cosine and filter indexes first.

`phase2_schema_guard` currently rejects any new table. Before deploying the new
migration, replace its frozen baseline with an explicit reviewed Phase 3 baseline
and reference checks; continue rejecting unexpected tables/views/policies/grants.
Do not remove the guard or introduce a blanket allowlist. Retained index/snapshot
references block physical cleanup; no automatic chunk/artifact deletion. Retest
recovery dry-run/apply, expired work and unknown-schema refusal. Publishing and
snapshot implementation remain Phase 4.

### Offline evidence

`phase-3-fixtures.json` contains synthetic Arabic/English evidence, expected facts,
fallbacks, cross-owner/assistant denials and document/user prompt-injection cases.
`backend/tests/test_phase3_contracts.py` validates request examples, fixture isolation,
source excerpts, fallback invariants, and rejection of deliberately corrupted
examples. These are executable contract/fixture checks, NOT RAG, API, SQL/RLS or
provider integration tests. AC-008/009/017/018 remain implementation acceptance
targets; passing these checks does not mark those criteria implemented.

## Phase 3 Task 2: deterministic chunking

Implementation: `backend/src/assistant_builder/chunking.py`. This is a pure
component, not an API or indexing integration. An eventual owner-scoped service
will read persisted `knowledge_file_text`, construct `SourceText` records and call
the `Chunker` interface. It must still perform authentication/RLS; matching IDs
inside this component are validation, not authorization.

`DeterministicChunker` accepts up to five sources from one owner/assistant and
returns an immutable tuple only after the entire corpus passes limits. File UUID
ordering is canonical; ordinals are zero-based within each file. Empty corpus
returns no chunks; empty/whitespace-only source, duplicate files, mixed ownership,
invalid Unicode or invalid extraction version fails explicitly.

Tokenizer decision: maintained `tiktoken` with provisional `cl100k_base`, locked
to the installed version in `backend/uv.lock` (0.14.0 for this implementation).
This is a local tokenizer choice, NOT an embedding model/provider choice.
The `Tokenizer` protocol isolates it from chunking. `encode_ordinary` treats
special-token-looking document text as ordinary untrusted text. No custom BPE,
word-count estimate or whitespace tokenizer is implemented.

Algorithm: tokenize the unchanged source once, obtain character offsets, form
600-token windows with approximately 100-token overlap, round to complete Unicode
characters, and re-tokenize each source slice to enforce at most 600 tokens.
Do not normalize whitespace, Arabic, combining marks or newlines. Unicode
code points remain intact; a boundary may split a grapheme cluster or sentence.
Overlap is exact on simple token-aligned text and approximate around multibyte
boundaries. Forward progress and full source coverage are required.

Offsets are zero-based, end-exclusive Python Unicode character indices into the
persisted extracted text, not UTF-8 byte positions, JavaScript UTF-16 positions,
graphemes, PDF pages or original document offsets. `Chunk.validate_source` rejects
invalid ranges, text mismatches, changed hashes, identities or extraction versions.
Every chunk carries owner/assistant/file UUIDs, extraction version, source SHA-256,
chunker/tokenizer fingerprint, ordinal, offsets, token count and exact text.
UUIDv5 identity covers those source/configuration identifiers; identical inputs
produce identical IDs, while extraction/tokenizer/window changes invalidate IDs.
These predictable IDs are never authorization tokens.

100,000 source tokens and 200 chunks are aggregate limits over all supplied files.
Overlap counts toward chunk/embedding workload, not original source-token total.
At most 2,000,000 characters per file preserves the existing Phase 2 extraction
bound before tokenization. Configurable limits can be lowered, not raised beyond
the approved bounds. No partially returned generator or silent truncation on error.
Pure CPU work is size-bounded, not a hard wall-clock/memory sandbox; future
preparation orchestration must enforce its deadline and measure worst-case inputs.

Bootstrap: tiktoken may fetch its public vocabulary the first time it is constructed.
Warm/cache `cl100k_base` during environment preparation, then run offline; source
text is never uploaded. Preserve that cache in future deployment images. Missing
vocabulary/cache initialization is an operational failure, not an empty corpus.

Before provider-backed indexing: validate this encoding against the chosen
embedding model's documented tokenizer and actual Arabic/English token usage,
input limits and special-token handling. If incompatible, supply the maintained
model tokenizer through the interface and issue a new fingerprint/reindex.
Reconfirm 100,000-token budgets with that tokenizer. Chunking tests do not validate
embedding dimensions, provider billing or retrieval quality.

Library behavior reference: [tiktoken encoding and Unicode offsets](https://github.com/openai/tiktoken/blob/main/tiktoken/core.py).

### Task 3A Gemini validation harness (2026-10-21)

`backend/scripts/validate_gemini.py` is an isolated synthetic probe, not a runtime
provider adapter. It reuses the bilingual Task 1 fixtures and Task 2 tokenizer.
Approved candidates: `gemini-embedding-2` requesting 768 dimensions and
`gemini-3.5-flash-lite`. These are requested settings, not live-verified results.

Prerequisites: `GEMINI_API_KEY` in backend/.env or the process environment;
operator confirmation in AI Studio that the key's project is Free tier with
free quota for both models. Key presence does not prove billing status. The
script does not query billing or change it. Do not confirm a paid-tier project.

From backend, safe mode (zero requests):
` .\.venv\Scripts\python.exe scripts/validate_gemini.py `

Only after confirming the above prerequisites, run once:
` .\.venv\Scripts\python.exe scripts/validate_gemini.py --live --confirm-free-tier `

Maximum eight requests per invocation: three individual embeddings (English,
Arabic, mixed), three matching native token counts, and two OpenAI-compatible
generation checks (grounded bilingual JSON and insufficient evidence). Stops on
first failure; no retries, redirects, database access, private documents, or
automatic paid/provider fallback. Each request has a 12-second total deadline
and a 3-second connection timeout. Do not rerun a failed live probe without
reviewing the remaining authorized request budget.

The sanitized JSON report includes attempted requests, observed vector counts,
dimensions, finite/nonzero norms, token counts versus cl100k_base, numeric usage
when supplied, and latency. It excludes credentials, vectors, raw answers and
raw provider errors. Missing usage is recorded as an empty object, not zero cost;
countTokens is not billing usage. One vector per request is tested; batch
ordering/aggregation, retrieval quality, and production latency remain untested.
Generation checks are bounded smoke assertions, not a complete quality review.
The no-evidence generation probe tests model behavior only; the eventual runtime
must still return its exact configured fallback locally without generation.

Observed on 2026-10-21: key present; operator confirmed free-tier access.
The sandboxed invocation stopped after one transport failure without a provider
response. A network-enabled invocation then stopped on its first embedding
request with HTTP 403. No further calls were made. Total attempts across both
invocations: two; provider HTTP responses: one. No vectors, provider token usage,
generation results, or successful latency measurements were obtained. HTTP 403
alone does not establish the cause or model availability; account/key access
must be resolved before another explicitly reviewed run. No credentials or raw
provider error bodies were recorded.
28 harness tests passed; 95 focused tests passed; backend regression suite:
207 passed, 27 PostgreSQL integration tests skipped, three existing warnings.
Task 3B approval remains pending live validation and human review. UI-06's live
smoke-test gate is unchanged.

REST references: [embedding requests](https://ai.google.dev/api/embeddings),
[token counting](https://ai.google.dev/api/tokens),
[OpenAI-compatible generation](https://ai.google.dev/gemini-api/docs/openai).

### Groq synthetic validation observations (2026-10-21)

`backend/scripts/validate_groq.py` reuses the synthetic fixtures and sanitized
usage handling. It uses GROQ_API_KEY, an operator-confirmed Free plan, a fixed
Groq endpoint, no redirects/retries, and the existing 12-second total/3-second
connect deadlines. It is not a production adapter. No new dependencies.

Exactly five live requests completed: one model lookup (0.664 seconds) confirming
`openai/gpt-oss-20b`, and four generation requests. Settings: reasoning_effort=low,
reasoning_format=hidden, max_completion_tokens=512. Free-tier billing basis is
the owner's console confirmation, not a billing API inspection.

| Synthetic case | Seconds | Prompt tokens | Completion tokens | Outcome |
| --- | --- | --- | --- | --- |
| English | 0.444 | 141 | 25 | Correct: Returns are allowed within 14 days. |
| Arabic | 0.343 | 154 | 34 | Correct and concise: 14 يوماً. |
| Mixed | 0.402 | 171 | 33 | Correct: أربع عشرة يومًا. / Fourteen days. |
| No evidence | 0.393 | 123 | 23 | Exact configured English fallback |

The first run stopped after request four because the mixed-answer assertion
required digits. Human inspection found the answer factually correct but not
following the requested Western-digit formatting. The assertion now accepts
written numbers; a regression test covers that false negative. Only the fifth
remaining request was executed separately with --fallback-only. Earlier requests
were not repeated. Total reported usage: 589 prompt + 115 completion = 704 tokens.

72 focused mocked/contract tests passed, including timeout, 401/403/429, no retry,
response validation, written numbers and the one-request continuation. No live
failure injection or rate-limit exhaustion was attempted. Model availability is
observed; organization quotas (30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD) were
reported by the owner, not load-tested. Four short responses do not establish
production tail latency or comprehensive Arabic/retrieval quality.

AC-008/009/017/018: provider smoke evidence only, not completed Playground
acceptance. Current draft integration and server-side exact fallback still need
implementation. Runtime must skip generation when relevant evidence is absent.
GO for a reviewed generation adapter implementation; NO-GO for production release
or vector-schema decisions based on this probe alone. Embeddings and UI-06 live
verification remain unresolved. No database or production settings changed.

### Groq generation boundary implementation

`backend/src/assistant_builder/generation.py` provides the async AnswerGenerator
protocol, GroqAnswerGenerator, immutable Behavior/Evidence/Answer/Citation/Usage
records, and answer_from_evidence. No route or full RAG service consumes it yet.
The future caller must authorize the owner/assistant, select sufficiently relevant
current evidence, enforce readiness and budget/concurrency, and recheck freshness
before delivering an answer. Empty evidence returns the exact fallback locally;
failed retrieval must not be passed as an empty successful result. Generation
failures propagate separately with fixed safe codes.

Configuration: AI_BASE_URL, AI_API_KEY (SecretStr), AI_MODEL, AI_TIMEOUT_SECONDS
(default and maximum 12 seconds). No secret is copied from GROQ_API_KEY automatically.
The Groq-specific adapter allows only HTTPS api.groq.com/openai/v1; another provider
uses a replaceable adapter without changing the domain interface. There are no
redirects, retries, environment proxies, provider SDK dependencies or prompt logs.
HTTP clients close after each call; application-scoped pooling can be considered
when wiring the lifecycle, without changing this boundary.

Requests use low reasoning effort, hidden reasoning, JSON-object mode and a
512-token completion ceiling. UTF-8 byte lengths conservatively bound BPE text
tokens: 1,000 message, 3,000 evidence, 6,000 total including a 512-token framing
reserve; 4,000 message characters and five sources also apply. These limits are
intentionally stricter than model-token counts, especially for Arabic, and do not
silently truncate. Provider-added framing has not been calibrated for this new
JSON request shape. Returned usage is checked and exposed when supplied; missing
usage is None, never free/zero. Budget accounting and reservations remain future
orchestration work, and must precede route integration.

Provider response size is bounded to 64 KiB. Incomplete output, tool calls,
malformed JSON, unknown/duplicate citations, invented or blank excerpts and
provider-generated metadata are rejected. File IDs/names come only from supplied
server evidence. Citation integrity does not prove entailment: a valid quote can
accompany an unsupported claim, and prompt instructions are not a guaranteed
defense against injection. Tests explicitly preserve this limitation; broader
grounding evaluation is required before production release. The answer is plain
text; future clients must not render it as HTML.

Safe failure codes: generation_configuration, generation_input_limit,
generation_auth (401/403), generation_rate_limited (429),
generation_model_unavailable (404), generation_timeout, generation_unavailable,
generation_invalid_output. Unknown non-200 responses remain safe unavailable
errors; raw provider details never enter application exceptions.

Traceability: AC-008/009 current behavior and supplied evidence boundaries;
AC-017 local exact fallback and distinct failures; AC-018 server-only model
configuration. This is component coverage, not completed Playground acceptance.
Mocked tests include Arabic, fabricated evidence, injection boundary handling,
timeouts, rate limits, authentication failures, response caps and usage checks.
No live requests were made for this implementation; JSON-mode compatibility and
grounding quality are not implied by the earlier plain-text smoke test.

### OpenAI embedding validation observations (2026-10-21)

`backend/scripts/validate_openai_embeddings.py` reads only OPENAI_API_KEY for
credentials and targets https://api.openai.com/v1/embeddings. Groq configuration
is unchanged. The owner confirmed available credit and a $0.001 validation cap.
Four requests were made without retries, using only the existing synthetic
English/Arabic/mixed fixtures. Model: text-embedding-3-small; dimensions: 768;
encoding_format: float. No migrations or application integration.

| Input | Vectors | Actual dimensions | Reported/local tokens | Seconds |
| --- | --- | --- | --- | --- |
| English | 1 | 768 | 18 / 18 | 2.613 |
| Arabic | 1 | 768 | 52 / 52 | 0.183 |
| Mixed | 1 | 768 | 70 / 70 | 0.852 |
| Three-input batch | 3 | 768 each | 140 / 140 | 0.264 |

All vectors contained finite numbers with finite nonzero norms. Model access and
cl100k_base usage compatibility passed for these fixtures. Total observed tokens:
280; estimated cost at $0.02/million: $0.0000056 (not an inspected invoice).
All requests completed within 12 seconds; this is not a tail-latency benchmark.

Overall result is PARTIAL/FAILED: indices were valid and one vector per input was
returned, but coordinate comparisons against individual results passed only for
Arabic. English and mixed differed beyond rel_tol=1e-4/abs_tol=1e-6. This does not
establish incorrect ordering: numerical variation is also possible. Vectors were
not persisted, so differences cannot be diagnosed retrospectively. No additional
requests were sent. Do not mark batch equivalence/order verified. Before adapter
approval, a reviewed diagnostic should compare cosine similarity, maximum error,
and cross-input matches without simply loosening checks to obtain a pass.

19 offline harness tests cover batching/index reconstruction, malformed vectors,
dimension errors, authentication/quota errors, timeouts and fail-closed handling.
Provider expectations: [OpenAI embeddings guide](https://developers.openai.com/api/docs/guides/embeddings)
and [model pricing](https://developers.openai.com/api/docs/models/text-embedding-3-small).
The key is time-limited according to the owner; durable credential replacement
remains necessary before production. Generation remains Groq. Embedding adapter
GO/NO-GO: NO-GO pending batch-consistency investigation and human review.

#### Follow-up batch diagnostics (2026-10-21)

Owner explicitly approved four additional synthetic requests within $0.001.
Exactly four completed, with no retries: 280 tokens, estimated $0.0000056.
Input strings are constructed once and reused unchanged; model, dimensions and
encoding_format are identical. Response arrays are reconstructed using unique
integer indices, not assumed array order. Reversed arrays are tested offline.

Cosine matrix (rows batch, columns individual; English, Arabic, mixed):

| | English | Arabic | Mixed |
| --- | --- | --- | --- |
| English | 0.999999600820 | 0.480321020430 | 0.853628824134 |
| Arabic | 0.480313279865 | 1.000000000000 | 0.781729410654 |
| Mixed | 0.853637640307 | 0.781794533687 | 0.999999627125 |

| Input | Maximum absolute error | Mean absolute error | L2 error |
| --- | --- | --- | --- |
| English | 0.0001220703125 | 0.00002500453653 | 0.000904344702 |
| Arabic | 0 | 0 | 0 |
| Mixed | 0.0001220703125 | 0.00002352691566 | 0.000895615679 |

Nearest matches are [0,1,2]; minimum diagonal advantage is 0.1463619868.
Observed norm differences are below 0.000238. All dimensions remain 768; finite
values and token counts pass. Latencies: 1.603/0.286/5.470/0.385 seconds.
Evidence supports small numerical variation, not a swap, for these fixtures.
The provider's internal cause (precision, batching implementation, etc.) is unknown.

The live diagnostic still returned failed under the old coordinate gate. Offline
assessment of its recorded metrics passes the revised gate: cosine >=0.999998
(unit-vector L2 <=0.002), norm difference <=0.001 and diagonal advantage >0.004.
The angular bound limits cosine-score perturbation against a fixed unit query to
0.002; twice that bounds pairwise score uncertainty. This is a smoke-test numerical
tolerance, NOT a retrieval relevance threshold or a provider guarantee. Borderline
retrieval decisions still require calibration. Coordinate errors remain reported.
Dimension, finite-value, index uniqueness/count and tokenizer checks are unchanged.
No extra calls were used to rerun the revised gate. 22 diagnostic tests and 34
chunking tests passed (56 total), including small noise, swaps, ambiguous matches,
norm/direction drift, duplicate indices and reversed response arrays.

Recommendation superseding the earlier blocker: GO for a reviewed EmbeddingProvider
adapter implementation using this candidate; not production readiness or migration
approval. Preserve version/dimension tracking and plan replacement of the expiring
credential. Semantic retrieval quality has not been evaluated by these diagnostics.

### OpenAI embedding adapter implementation

`backend/src/assistant_builder/embeddings.py` defines EmbeddingProvider.embed(texts)
and OpenAIEmbeddingProvider. A one-element tuple embeds a single text; a bounded
tuple embeds a batch. EmbeddingResult returns immutable vectors in input order,
model/dimension identity and verified token usage. No database, retrieval, route
or generation integration is included.

Runtime configuration is independent: EMBEDDING_BASE_URL=https://api.openai.com/v1,
EMBEDDING_API_KEY (SecretStr), EMBEDDING_MODEL=text-embedding-3-small,
EMBEDDING_DIMENSION=768, EMBEDDING_TIMEOUT_SECONDS=12,
EMBEDDING_MAX_BATCH_SIZE=8, EMBEDDING_MAX_INPUT_TOKENS=4800.
No automatic aliases to AI_API_KEY or the validation script's OPENAI_API_KEY.
The existing OPENAI_* example settings are preserved; use EMBEDDING_* for runtime.
Operators may lower batch/token/timeout limits, not increase the approved bounds.
The model is read from configuration and restricted to the validated candidate;
changing models requires a new validation/reindex decision, not silent substitution.

The existing cl100k_base tokenizer counts every input with no normalization or
truncation. Empty/blank/invalid-Unicode inputs fail before dispatch. A 32,000-character
pre-tokenization bound limits local processing. Vocabulary caching must be prepared
before offline startup. Total batch tokens cannot exceed 4,800; no implicit splitting
or retries create extra requests. HTTPX follows the generation adapter's lifecycle
pattern, closes per-call clients, disables proxies/redirects/retries, and enforces a
12-second wall-clock deadline plus at most three seconds for connection establishment.
Only the approved HTTPS OpenAI host/path receives credentials.

Responses are bounded to 512 KiB. Unique integer indices must cover every input;
array order is irrelevant. Missing, duplicate, boolean or out-of-range indices,
wrong model, dimension mismatches, nonnumeric/nonfinite/zero vectors and malformed
usage fail closed. Usage must match the locally counted input tokens; drift requires
investigation rather than silently accepting unknown billing. Norms are validated
but vectors are not renormalized or rounded. Approximate batch/single equivalence
is a diagnostic, not an extra runtime request.

Safe errors: embedding_configuration, embedding_input_limit, embedding_auth,
embedding_quota_or_rate_limited, embedding_model_unavailable, embedding_timeout,
embedding_unavailable, embedding_invalid_output, embedding_dimension_mismatch.
No prompts, raw provider errors or keys are logged. Vectors are hidden in result
representations. No new dependencies or live provider requests were used.

Next-task readiness: GO for reviewed versioned-index/repository/schema implementation;
this does not authorize migration execution. Persist provider/model/dimension/index
identity, enforce owner isolation, budget reservations and recovery compatibility,
and replace the time-limited credential before deployment. Retrieval relevance and
end-to-end Playground acceptance remain unverified.

### Phase 3 Task 3B: local versioned indexing and pgvector migration

Local implementation: `backend/src/assistant_builder/indexing.py`, SQLAlchemy index
models in `models.py`, and additive migration
`backend/alembic/versions/0004_versioned_knowledge_indexes.py`. The migration was
rendered offline only; it was not executed against local PostgreSQL or Supabase.
It creates `knowledge_indexes`, `knowledge_index_sources`,
`knowledge_index_batches`, and `knowledge_chunks`, then adds the nullable active
index pointer to `assistants`. Composite foreign keys bind every index, source,
batch, and chunk to the same assistant and owner. FK delete behavior is RESTRICT
by default; no runtime DELETE permission is granted. Index source rows and vector
artifacts therefore remain available for audit/recovery.

`knowledge_chunks.embedding` is `public.vector(768)`. Migration 0004 deliberately
does not run `CREATE EXTENSION`; its preflight stops unless the pgvector extension
and its `public.vector` type already exist in `public`, the restricted
`assistant_runtime` role exists without superuser or BYPASSRLS, the existing
assistant table still has forced owner RLS, and no conflicting index
tables/column/policies exist. It relies on the runtime role's existing `public`
schema USAGE, applies forced RLS to all four new tables, and grants only
owner-scoped SELECT/INSERT plus the specific state and activation-column UPDATE
privileges required by the service. No Data API policies or DELETE grants are
created. Read-only live preflight confirmed pgvector 0.8.2 in `public`, revision
`0003_knowledge_files`, and no pre-existing indexing objects. Migration 0004 has
been aligned to that schema but remains unapplied pending review and separate
authorization.

The index lifecycle is `building -> ready | failed | superseded`. The active
assistant pointer changes in the same transaction that marks the complete version
ready. Each version records a sorted source manifest, content/extraction hashes,
chunker/tokenizer fingerprints, embedding provider/model, dimension, and version.
Chunk IDs persisted in the database are stable within an index version and unique
across versions. Draft attachment reservation, extraction completion, and removal
clear the active pointer; a matching already-ready index can be reactivated after
a failed/non-eligible upload without another provider call. Stale/removed sources
cannot activate an index. Old immutable rows remain stored and are not retrievable
through an active pointer.

`start()` rejects empty or not-ready knowledge and checks the complete corpus
against the existing 100,000-source-token/200-chunk limits before provider work.
Embedding requests are split to at most 8 chunks and 4,800 tokens. The per-index
reserved embedding cost is capped at $0.10; provider timeout and no-automatic-retry
behavior remain in the adapter. A global $1/day AI budget is specified by the
contract but is not yet enforced by this owner-isolated database service: enforcing
a global cross-owner ledger through the restricted runtime role would weaken
owner isolation. This requires a separate approved quota mechanism before enabling
unattended production indexing.

Each batch is claimed with a durable operation token and 60-second lease before
the provider call. Provider I/O occurs outside the database transaction. Vectors
must match model and dimension, have finite nonzero values, and preserve input
count/order. Only then are chunks and completed-batch state committed. Provider
failures are distinct from indexing/source failures. A changed manifest supersedes
the build. Expired uncertain provider attempts are fenced; recovery leaves them
failed/uncertain unless an operator explicitly approves a retry because retrying
may incur duplicate cost. Completed batches are not repeated. Partial vectors stay
in a non-active version and cannot be served.

Offline verification: `backend/tests/test_versioned_indexing.py` covers owner
scoping, idempotency, readiness activation, chunk/embedding limits, second-batch
failure visibility, invalid vectors, stale-source supersession, lease fencing, and
rollback of an empty build. Migration SQL assertions verify the public-schema
extension prerequisite, composite ownership relationships, vector dimension,
forced RLS, restricted grants and non-destructive shape. The global $1/day AI
budget is not enforced by the migration or owner-scoped indexing service; it must
be addressed before unattended provider-backed indexing is enabled. No PostgreSQL
RLS behavior, migration execution, provider request, or live database write was
verified by these offline checks. After the schema correction, the backend suite
reported 341 passed and 27 PostgreSQL integration tests skipped (Docker was not
available); compilation passed with no errors. The migration may be considered for separately
authorized execution only after the updated offline checks pass and a final
read-only preflight confirms prerequisites remain unchanged. NO-GO for retrieval
activation now. Playground, retrieval, relevance calibration, and live two-owner
RLS tests remain out of this task.

### Phase 3 — Initial synthetic retrieval-threshold calibration

One controlled embedding request sent eight fixed synthetic inputs (three short
English, Arabic, and mixed-language passages plus three matching questions and
two unrelated questions) to the configured OpenAI embedding adapter. It returned
768-dimensional vectors for all inputs and reported 229 tokens. Exact cosine
similarities produced a maximum irrelevant-passage score of `0.394631` and a
minimum expected-match score of `0.674235`. The midpoint `0.534433` is recorded as
the initial configurable threshold in `backend/.env.example`; it is a calibration
result for these fixtures, not a universal relevance guarantee. Recalibrate with
representative business documents and queries before a broader launch, and after
changing the embedding model or corpus characteristics. No document or user data
was sent. This diagnostic did not access or modify Supabase.

### Phase 3 - Follow-up live retrieval calibration (2026-10-22)

The developer reported a bounded calibration against the existing ready index using four known-answer and three unknown-answer questions. It recommended `0.30347`, which is now configured in the local `backend/.env`. The local environment file and index-specific calibration artifacts are excluded from version control; this record contains no document text or personal data. Focused offline retrieval and calibration tests passed (27 passed) after the local setting was applied. No provider call, reindex, or database change occurred during that configuration update. This threshold is specific to the calibrated data and is not a universal relevance guarantee.

Playground status remains unresolved: the latest reported request failed with `generation_input_limit`. Diagnose and verify that error before accepting the Playground or closing Phase 3.

### Phase 4 - P4-04 local public chat implementation (2026-10-23)

The local FastAPI implementation now exposes the approved public assistant,
conversation-creation, and visitor-message contracts. Public access is disabled by
default (`PUBLIC_CHAT_ENABLED=false`). Enabling the bounded demo requires an
operator-provisioned `PUBLIC_DATABASE_URL` for the restricted
`assistant_public_runtime` role, complete existing server-side AI configuration,
and one or two tester secrets represented by SHA-256 digests in
`PUBLIC_DEMO_TOKEN_SHA256`. Each request must carry the tester's `X-Demo-Access`
credential. Conversation creation returns a random visitor capability once;
subsequent messages send it in `X-Visitor-Token`. Only its SHA-256 digest is stored.
Do not place either token in a URL, logs, browser storage, source control, or the
widget snippet. No actual demo tokens or credentials are recorded here.

The public database connection is separate and startup validation checks the
restricted role and denied draft/accounting privileges. Resolution reads only the
active immutable published snapshot. Query retrieval is pinned to that snapshot's
stored index/source manifest; draft assistants, current draft files, and owner
history are not used. Internal citation membership and excerpts are validated,
while public responses omit citations and private source metadata. Turns persist a
pending record before provider I/O, use per-conversation request IDs for idempotency,
and are finalized under the same assistant publication advisory lock used by the
publisher. If the active snapshot changed during generation, the generated text is
discarded and the durable turn is marked `version_rejected`. Provider outcomes that
cannot safely be replayed remain terminal/uncertain; there is no automatic AI retry.

The demo uses bounded process-local rate and concurrency controls (30 requests per
minute per source-IP/public-assistant pair, at most two in-flight requests per
public assistant and four public requests globally per application process), a
16-KiB POST body limit, and the existing embedding/generation guards plus a
30-second API deadline. Client IP comes from the direct ASGI peer; forwarded headers
are not trusted. The limiter is intentionally single-process and is not a durable
cross-worker control. The shared accounting schema is retained but its reservation
functions are not called in this tester-only demo. These controls do not provide a
monetary ceiling. Before unrestricted public launch, shared budget reservations and
settlement, verified pricing/quota, cross-worker rate/concurrency controls, and a
separate authorized live security/quality review are mandatory. The public API is
not a launch-ready widget, and no widget or owner history UI was implemented in
P4-04.

Local verification: 19 focused offline API/service tests passed. All 10 tests in the
P4 PostgreSQL integration module passed against a disposable PostgreSQL 16/pgvector
database, exercising the restricted public role's RLS/grants, draft and accounting
denial, fallback-only chat, capability-backed conversation, idempotent replay, and
idempotency conflict, indexed snapshot retrieval without private citation projection,
and publish-during-generation rejection. The full offline backend suite passed 442
tests with 38 opt-in PostgreSQL tests skipped; compilation passed. No live Supabase
resource or AI provider was used.

### Phase 4 — P4-05 owner conversation history API

P4-05 adds authenticated owner-only read endpoints over the existing
`visitor_conversations` and `visitor_turns` records. It does not add a visitor
history endpoint, new persistence tables, or history UI.

| Route | Request | Success | Failure |
| --- | --- | --- | --- |
| GET `/assistants/{assistant_id}/conversations?limit=20&cursor=...` | Verified owner bearer session; limit 1–100; optional stable cursor | Page of conversation ID, created/last-activity timestamps, safe latest status/outcome, latest published version, and next cursor | 401; uniform 404 for unknown or other-owner assistant; 422 invalid limit/cursor; generic 503 on persistence failure |
| GET `/assistants/{assistant_id}/conversations/{conversation_id}?limit=20&cursor=...` | Verified owner bearer session; limit 1–100; optional stable turn cursor | Ordered turns containing user and saved assistant messages, timestamps, safe status/outcome, immutable published version, and next cursor | 401; uniform 404 for unknown or cross-owner/cross-assistant conversation; 422 invalid limit/cursor; generic 503 on persistence failure |

Both routes derive owner identity only from the validated Supabase session and run
with the existing transaction-local owner context. The service also filters on
`owner_id` and `assistant_id`; forced RLS remains an independent boundary. The
cursor encodes the stable timestamp-plus-UUID ordering tuple and is not an
authorization credential. Conversation pages order newest first; turn pages order
oldest first. Default and maximum page sizes are 20 and 100. Conversation summaries
read only the newest associated turn and do not count an unbounded conversation on
every list request.

Detail exposes only saved user/assistant text, event timestamps, safe state
(`pending`, `completed`, `fallback`, `failed`, `uncertain`, or `version_changed`),
validated outcome (`grounded`/`fallback`), and published version number. Unfinished
or failed turns show the visitor's submitted text and a safe status, never an
assistant answer that was not durably saved. Unknown/inconsistent persistence states
fail closed as `failed`. The API never selects or returns visitor-token hashes,
request/input hashes, internal error codes, owner/publication/snapshot IDs, prompts,
credentials, or provider metadata. Cross-owner and cross-conversation access has a
uniform 404 response. Persistence failures return a generic 503 without exception
details. Idempotency remains the existing per-conversation unique request ID; this
API is read-only and does not retry or alter visitor turns.

PostgreSQL verification also confirms history retains the version for each original
turn after republishing: old conversations remain associated with their original
snapshot, while new conversations show the newly active version. No migration was
required. P4-05 has local tests only and awaits human review; its successful local
verification is recorded in PLAN-001.
