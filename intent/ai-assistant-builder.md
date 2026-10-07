# Intent: AI Assistant Builder

## Problem

Business owners with websites receive many customer questions, and some questions do not get answered. An embedded assistant should solve part of this customer service problem by answering repetitive customer questions using information the business provides.

## Users

The main users are business owners who have websites and may have no AI or programming experience. Business owners have their own accounts and can access and manage only their own assistants and associated data.

## Goals

- Let a business owner easily create, configure, and publish a useful AI assistant.
- Help the assistant answer customer questions accurately based on the business's provided knowledge.
- Reduce the need to manually answer repetitive customer questions.
- Let the business owner update the assistant's knowledge and behavior when needed.
- Let the owner embed the published assistant into their website with minimal effort.
- Let a business owner create and manage multiple assistants from their account.

## Workflows

The business owner provides knowledge by uploading PDF and DOCX files. The owner can list and view the knowledge files associated with an assistant and remove a knowledge file. To replace a file, the owner may remove the old file and upload a new one. The owner configures the assistant's name, role, knowledge files, colors, response style, tone, and a fallback message for questions the assistant cannot answer from the provided knowledge.

A business owner can create more than one assistant and manage the assistants associated with their account.

Before publishing, the owner may use an interactive chat playground inside the platform. The playground uses the assistant's current configuration and uploaded knowledge so the owner can verify responses and make changes. Using the playground is not required before publishing.

After publishing, the owner receives a simple embed code snippet to copy and paste into their website. The embedded assistant appears as a chat widget and connects to the published assistant without additional coding or configuration.

The assistant keeps basic conversation history from website visitors. The owner can view conversations associated with one of their assistants, open a conversation, and view its messages and timestamps. Advanced analytics, search, export, sentiment analysis, and visitor identification are not part of the MVP.

When the owner changes knowledge or behavior for a published assistant, the changes are saved as a draft. They become available to the public assistant only after the owner publishes or updates it again.

The assistant's responses must be grounded in retrieved business knowledge. When sufficient relevant knowledge cannot be found for a question, the assistant returns the owner's configured fallback message rather than generating a business-specific answer.

## Scope

### In scope

- Creating and configuring specialized AI assistants.
- Providing assistant knowledge through PDF and DOCX files.
- Supporting PDF and DOCX knowledge files for the MVP.
- Listing and viewing the knowledge files associated with an assistant.
- Removing a knowledge file; replacing a file can be done by removing the old file and uploading a new one.
- Configuring the assistant's name, role, colors, response style, tone, and fallback message.
- Creating and managing multiple assistants under a business owner's account.
- Testing the assistant in an interactive chat playground before publishing, without making that testing a publishing prerequisite.
- Publishing an assistant.
- Providing an embeddable chat widget through a copy-and-paste code snippet.
- Updating the assistant's knowledge and behavior when needed.
- Viewing an assistant's conversations, including each conversation's messages and timestamps.

### Out of scope

- Specific AI providers, vector databases, infrastructure, or implementation technology.
- Separate WordPress, Shopify, React, or other platform-specific integrations.
- Advanced analytics.
- Conversation search, export, sentiment analysis, and visitor identification.
- An automated answer-quality evaluation system.
- Authentication implementation details such as JWT, OAuth, or Auth0.

## Constraints

- The platform should be usable by business owners without AI or programming experience.
- Core assistant creation, configuration, testing, publishing, and knowledge-management workflows must not require the business owner to configure AI model parameters or write code.
- The assistant should base answers on the business's provided knowledge.
- Responses must be grounded in retrieved business knowledge. When sufficient relevant knowledge cannot be found for a question, the assistant must return the owner's configured fallback message rather than generate a business-specific answer.
- Website embedding should work on any website that allows the owner to insert the provided JavaScript embed snippet.
- Website embedding should require no additional coding or configuration beyond copying and pasting the provided snippet.
- Changes to a published assistant's knowledge or behavior should require a new publish or update action before they appear publicly.
- The intent remains a draft until unresolved decisions are clarified and it is explicitly approved.

## Open questions

None identified for the current MVP intent.

Status: approved
