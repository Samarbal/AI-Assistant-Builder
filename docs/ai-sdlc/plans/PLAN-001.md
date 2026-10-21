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
→ Phase 4 **planned** → Phase 5 **planned**.

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

Status: Phase 3 implementation is in progress. Versioned indexing, semantic
retrieval, RAG orchestration, authenticated Playground API/UI, and indexing
preparation controls are implemented locally. Retrieval calibration succeeded
with four known-answer and three unknown-answer questions; the resulting local
`RETRIEVAL_MIN_SIMILARITY` is `0.30347`. The Playground is not ready for acceptance:
the latest reported request failed with `generation_input_limit`. Diagnose and
verify that failure before marking Playground ready or Phase 3 complete. The UI-06
live smoke-test gate also remains pending.

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
