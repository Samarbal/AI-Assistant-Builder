# Phase 0 Contracts

Status: draft

This document turns the current SPEC-001 requirements and accepted ADRs into implementation contracts. It defines boundaries and observable behavior only; it does not define framework code, database tables, provider SDKs, or infrastructure configuration.

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

## Knowledge processing contract

- Accepted input extensions are PDF and DOCX only.
- An assistant may have no more than five knowledge files.
- Each file is at most 10 MB.
- Original files remain private in Supabase Storage.
- Metadata and processing state remain in Supabase PostgreSQL.
- Processing states must distinguish at least accepted, processing, ready, and failed.
- Only ready files may contribute chunks to retrieval.
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
