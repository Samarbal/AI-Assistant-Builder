# SPEC-001: AI Assistant Builder MVP

Status: draft

## Source and traceability

- Source: `intent/ai-assistant-builder.md`
- Traceability references use the current line numbers in the source intent.
- This specification remains draft for human review.

## Functional requirements

### FR-001: Assistant creation and ownership

The platform shall allow a business owner to create and manage multiple assistants under the owner's account. The owner shall access and manage only that owner's assistants and associated data.

Traceability: Intent lines 9, 18, 24, 46.

### FR-002: Assistant configuration

The platform shall allow the owner to configure an assistant's name, role, knowledge files, colors, response style, tone, and fallback message.

Traceability: Intent lines 22, 45.

### FR-003: Knowledge file management

The platform shall allow the owner to upload PDF and DOCX knowledge files, list and view knowledge files associated with an assistant, and remove a knowledge file. Replacing a file shall be supported by removing the old file and uploading a new file.

Traceability: Intent lines 22, 41-44.

### FR-004: Optional pre-publication playground

The platform shall provide an interactive chat playground inside the platform. The playground shall use the assistant's current configuration and uploaded knowledge so the owner can verify responses and make changes. Use of the playground shall not be required before publishing.

Traceability: Intent lines 26, 47.

### FR-005: Grounded responses and fallback

The assistant shall ground responses in retrieved business knowledge. When sufficient relevant knowledge cannot be found for a question, the assistant shall return the owner's configured fallback message rather than generate a business-specific answer.

Traceability: Intent lines 34, 67.

### FR-006: Publishing

The platform shall allow the owner to publish an assistant. Publishing shall not require prior use of the playground.

Traceability: Intent lines 26, 48.

### FR-007: Website embed snippet

After publishing, the platform shall provide a JavaScript embed code snippet that the owner can copy and paste into a website.

Traceability: Intent lines 28, 49.

### FR-008: Embedded chat widget

When the provided snippet is inserted into a website that allows JavaScript insertion, the embedded assistant shall appear as a chat widget and connect to the published assistant without additional coding or configuration.

Traceability: Intent lines 28, 68-69.

### FR-009: Basic conversation history

The platform shall retain basic visitor conversation history. For an assistant owned by the business owner, the owner shall be able to view its conversations, open an individual conversation, and view that conversation's messages and timestamps.

Traceability: Intent lines 30, 51.

### FR-010: Draft and published versions

When the owner changes the knowledge or behavior of a published assistant, the changes shall be saved as a draft and shall not become available to the public assistant until the owner performs another publish or update action.

Traceability: Intent lines 32, 50, 70.

## Non-functional requirements

### NFR-001: Owner usability

Core assistant creation, configuration, testing, publishing, and knowledge-management workflows shall be usable by business owners without AI or programming experience.

Traceability: Intent lines 9, 64-65.

### NFR-002: No model-parameter configuration or coding

The core workflows shall not require the business owner to configure AI model parameters or write code.

Traceability: Intent line 65.

### NFR-003: Minimal website embedding effort

Embedding shall require no additional coding or configuration beyond copying and pasting the provided JavaScript embed snippet.

Traceability: Intent lines 28, 69.

### NFR-004: Website compatibility boundary

Embedding shall target websites that allow the owner to insert the provided JavaScript embed snippet. Platform-specific integrations are outside this specification.

Traceability: Intent lines 56, 68.

## Acceptance criteria

Each criterion is intended to be verified by an automated test.

- AC-001: Given one business-owner account, when it creates two assistants, then both assistants are associated with that account, listed for that account, and independently manageable.
- AC-002: Given two business-owner accounts with assistants and associated data, when each account requests its assistants and associated data, then each receives only its own records.
- AC-003: Given an assistant, when the owner saves its name, role, colors, response style, tone, knowledge-file association, and fallback message, then reopening the assistant returns each saved value.
- AC-004: Given a PDF and a DOCX file, when the owner uploads both to an assistant, then both uploads are accepted and associated with that assistant.
- AC-005: Given an assistant with associated knowledge files, when the owner lists and views its knowledge files, then the uploaded files are returned as associated files with viewable file information.
- AC-006: Given an assistant with an associated knowledge file, when the owner removes that file, then it is no longer associated with or listed for the assistant.
- AC-007: Given an assistant with an old knowledge file, when the owner removes the old file and uploads a new PDF or DOCX file, then the new file is associated with the assistant and the old file is not.
- AC-008: Given an assistant with saved configuration and uploaded knowledge, when the owner sends a message in the playground, then the playground uses the assistant's current configuration and uploaded knowledge for the interaction.
- AC-009: Given an assistant with saved configuration, when the owner changes a configuration value and sends a new playground message before publishing, then the playground uses the changed current configuration.
- AC-010: Given an unpublished assistant with valid saved configuration, when the owner publishes it without opening or using the playground, then publishing succeeds.
- AC-011: Given a published assistant, when the platform generates its website integration output, then the output contains a JavaScript embed snippet.
- AC-012: Given a website that permits JavaScript insertion, when the owner inserts the generated snippet without additional assistant-specific coding or configuration, then a chat widget is rendered and its requests target the published assistant.
- AC-013: Given a visitor conversation through the embedded widget, when the owner opens the conversation list for that assistant, then the conversation is present and associated with that assistant.
- AC-014: Given an existing conversation, when the owner opens it, then the platform returns its messages and timestamps.
- AC-015: Given a published assistant, when the owner changes its knowledge or behavior and saves the change, then public-assistant requests continue using the previously published version until a publish or update action occurs.
- AC-016: Given the changed assistant from AC-015, when the owner performs publish or update, then subsequent public-assistant requests use the changed version.
- AC-017: Given a question for which sufficient relevant business knowledge is unavailable and an owner-configured fallback message, when the assistant responds, then the response equals the configured fallback message and does not contain a generated business-specific answer.
- AC-018: Given an owner using any core workflow, when the workflow is completed, then no AI model parameter input or code input is required from the owner.

## Open questions and ambiguities

- The intent has no open questions for the current MVP. No additional requirement is introduced here.
- The goals use qualitative terms such as easily, useful, accurately, and minimal effort, but provide no measurable thresholds. This specification preserves those goals without inventing thresholds; no additional acceptance criterion is created for them.
- The intent requires responses to be grounded in retrieved business knowledge but does not define a retrieval-quality threshold. AC-017 tests the specified fallback behavior when sufficient knowledge is unavailable without defining an evaluation system.
- The intent does not define a default fallback message because the owner-configured fallback is the stated MVP behavior.

## Out of scope

This specification does not define specific AI providers, vector databases, infrastructure, implementation technology, platform-specific integrations, advanced analytics, conversation search, conversation export, sentiment analysis, visitor identification, automated answer-quality evaluation, or authentication implementation details.

Traceability: Intent lines 53-60.
