# PLAN-001: AI Assistant Builder MVP

Status: draft

## Source and planning boundary

- Specification: `docs/ai-sdlc/specs/SPEC-001.md`
- Intent: `intent/ai-assistant-builder.md`
- Timeline: approximately 4.5 weeks for implementation.
- Backend direction supplied for planning: Python with FastAPI.
- This plan covers only the requirements and acceptance criteria in SPEC-001. It does not select an AI provider, database, vector store, infrastructure, framework beyond the supplied FastAPI direction, or authentication implementation.
- The specification file currently says `Status: draft`, although this request identifies it as approved. The plan remains draft and this status mismatch requires human review; neither source file is changed by this plan.

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

- Resolve the draft-status mismatch between the request and `SPEC-001.md` through human review without changing scope.
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

Required MVP work:

- Implement PDF and DOCX upload validation.
- Implement owner-scoped file listing and viewable file information.
- Implement removal and remove-then-upload replacement workflow.
- Add processing states and failure reporting so an unsuccessful file process cannot silently become usable knowledge.
- Connect processed knowledge to the assistant while keeping storage and retrieval implementations behind interfaces.

Tests and traceability: FR-003; AC-004, AC-005, AC-006, AC-007.

### Phase 3: Response orchestration and optional playground (5-6 days)

Required MVP work:

- Implement playground chat against the current draft configuration and uploaded knowledge.
- Apply grounded-response behavior and the owner-configured fallback when sufficient relevant knowledge is unavailable.
- Ensure current draft changes are reflected in playground requests.
- Handle unavailable, malformed, or failed knowledge retrieval and response generation with a safe failure result that does not invent business-specific content.

Tests and traceability: FR-004, FR-005; AC-008, AC-009, AC-017.

### Phase 4: Publishing, embed delivery, and visitor chat (5-6 days)

Required MVP work:

- Implement publish/update transitions from draft to public state.
- Verify that publishing can succeed without prior playground use.
- Generate and return a JavaScript embed snippet for a published assistant.
- Serve the embedded chat flow against the published version only.
- Record visitor conversations, messages, and timestamps.
- Provide owner-scoped conversation list and conversation detail views.

Tests and traceability: FR-006 through FR-010, NFR-003, NFR-004; AC-010 through AC-016.

### Phase 5: Hardening and MVP acceptance (3-4 days)

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
| FR-001; AC-001-002 | Owner-scoped assistant service, account boundary tests, cross-owner access denial tests. |
| FR-002; AC-003 | Configuration service and persistence contract tests for every configured field. |
| FR-003; AC-004-007 | File validation, association, listing/view, removal, and replacement tests. |
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

## Significant ADR candidates

These are candidates only; no ADRs are created by this plan:

- ADR-001: Persistence model and transaction boundaries for accounts, assistants, versions, files, and conversations.
- ADR-002: File storage and document-processing approach for PDF and DOCX uploads.
- ADR-003: Retrieval/indexing approach and the boundary between knowledge processing and response orchestration.
- ADR-004: AI provider abstraction and provider selection for grounded responses.
- ADR-005: Authentication and authorization model for owner isolation.
- ADR-006: Public embed and visitor-chat delivery boundary, including how published assistant identity is protected.
- ADR-007: Draft/published versioning and publish/update atomicity.
- ADR-008: Operational limits, retention, and failure recovery for visitor conversations and uploaded knowledge.

## Technical risks and assumptions

Risks:

- PDF/DOCX extraction quality may make grounding unreliable, especially for complex layouts or scanned documents.
- Retrieval may return insufficient or misleading context; the fallback boundary must remain conservative.
- Keeping draft and published behavior separate can create stale or partially published state if transitions are not atomic.
- Public embed traffic and visitor history create data-isolation, abuse, and operational-load risks.
- The 4.5-week window leaves little room for advanced document handling, broad compatibility testing, or rework after provider/storage decisions.

Assumptions:

- A usable account identity and owner context are available to the MVP, while the concrete authentication mechanism remains an ADR decision.
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
