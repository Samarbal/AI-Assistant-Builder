"""One-shot live indexing verification with synthetic data only.

Authenticates a dedicated Supabase test owner, creates one assistant and one
small DOCX through the existing FastAPI workflows, then invokes the existing
indexing service directly (there is intentionally no indexing HTTP route yet).
Test rows and the Storage object are retained; this script never deletes data.
"""
import asyncio
import getpass
import logging
import math
import sys
import warnings
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4

import httpx
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select

from assistant_builder.auth import SupabaseAuthVerifier
from assistant_builder.chunking import DeterministicChunker, TiktokenTokenizer
from assistant_builder.config import Settings
from assistant_builder.db import set_owner_identity
from assistant_builder.embeddings import OpenAIEmbeddingProvider
from assistant_builder.indexing import MAX_INDEX_COST_MICRO_USD, VersionedIndexService
from assistant_builder.main import create_app
from assistant_builder.models import (
    Assistant, KnowledgeChunk, KnowledgeFile, KnowledgeFileText,
    KnowledgeIndex, KnowledgeIndexBatch,
)
from signin_phase1 import sign_in, validate_auth_settings


FIXTURE_TEXT = (
    "Synthetic indexing verification only. The fictional demo code word is maple. "
    "This statement is test data and contains no customer or business information."
)


def require(condition, safe_message):
    if not condition:
        raise RuntimeError(safe_message)


def main():
    logging.disable(logging.CRITICAL)
    warnings.filterwarnings("error", category=getpass.GetPassWarning)
    if not sys.stdin.isatty():
        print("STOP: run this script from an interactive terminal for hidden password entry")
        return 2

    settings = Settings()
    validate_auth_settings(settings)
    # Provider configuration is checked before asking for credentials or writing data.
    provider = OpenAIEmbeddingProvider(settings)
    tokenizer = TiktokenTokenizer()
    if not settings.database_url or not settings.supabase_storage_key:
        print("STOP: restricted database and private Storage configuration are required")
        return 2

    email = input("Dedicated test owner email: ").strip()
    password = getpass.getpass("Test owner password (hidden): ")
    with httpx.Client(timeout=20, follow_redirects=False) as auth_client:
        token = sign_in(auth_client, settings.supabase_url, settings.supabase_anon_key,
                        email, password)
        del email, password
        owner = SupabaseAuthVerifier(settings.supabase_url, settings.supabase_anon_key,
                                     auth_client).verify("Bearer " + token)
    headers = {"Authorization": "Bearer " + token}

    app = create_app()
    with TestClient(app) as client:
        create = client.post("/assistants", headers=headers, json={
            "name": "Phase 3 indexing check " + str(uuid4())[:8],
            "role": "Synthetic test assistant",
            "colors": {"primary": "#526482", "accent": "#635BFF"},
            "response_style": "Concise", "tone": "Neutral",
            "fallback_message": "I cannot find that answer in the provided knowledge.",
        })
        require(create.status_code == 201, "Assistant creation failed")
        assistant_id = UUID(create.json()["id"])

        document = Document()
        document.add_paragraph(FIXTURE_TEXT)
        buffer = BytesIO()
        document.save(buffer)
        content = buffer.getvalue()
        upload = client.post(
            f"/assistants/{assistant_id}/knowledge-files", headers=headers,
            files={"file": (
                "phase3-synthetic-index-test.docx", content,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )},
        )
        require(upload.status_code == 201, "Synthetic DOCX upload failed")
        file_id = UUID(upload.json()["id"])
        require(upload.json()["processing_state"] == "extracted",
                "Synthetic document extraction did not complete")

        sessions = app.state.session_factory
        service = VersionedIndexService(
            sessions, DeterministicChunker(tokenizer), provider,
            tokenizer=tokenizer, embedding_model=settings.embedding_model,
            vector_dimension=settings.embedding_dimension,
        )
        index = service.start(owner.owner_id, assistant_id, uuid4())
        require(index.total_chunks == 1, "Test corpus did not produce exactly one chunk")
        with sessions.begin() as session:
            set_owner_identity(session, owner.owner_id)
            file_row = session.scalar(select(KnowledgeFile).where(
                KnowledgeFile.id == file_id, KnowledgeFile.owner_id == owner.owner_id,
                KnowledgeFile.assistant_id == assistant_id))
            source_text = session.scalar(select(KnowledgeFileText.extracted_text).where(
                KnowledgeFileText.file_id == file_id,
                KnowledgeFileText.owner_id == owner.owner_id))
            batch = session.scalar(select(KnowledgeIndexBatch).where(
                KnowledgeIndexBatch.index_id == index.index_id))
            require(file_row is not None and file_row.content_sha256 == sha256(content).hexdigest(),
                    "Uploaded source ownership or hash mismatch")
            require(source_text is not None and FIXTURE_TEXT in source_text,
                    "Persisted extracted text does not match the synthetic source")
            require(batch is not None and batch.state == "pending" and batch.attempts == 0,
                    "Index batch is not in its initial safe state")
            require(batch.reserved_cost_microusd <= MAX_INDEX_COST_MICRO_USD,
                    "Estimated index cost exceeds the approved per-index cap")
            require(batch.reserved_tokens <= 4800 and len(batch.chunk_ids) == 1,
                    "Index batch exceeds the approved single-chunk scope")
            reserved = batch.reserved_cost_microusd

        # One batch only. The provider adapter disables retries; any uncertain result
        # is left for the fail-closed operator recovery path.
        result = asyncio.run(service.advance(owner.owner_id, assistant_id, index.index_id))
        require(result.state == "ready" and result.completed_chunks == result.total_chunks == 1,
                "Index did not become ready after its single provider batch")

        with sessions.begin() as session:
            set_owner_identity(session, owner.owner_id)
            assistant = session.scalar(select(Assistant).where(
                Assistant.id == assistant_id, Assistant.owner_id == owner.owner_id))
            index_row = session.scalar(select(KnowledgeIndex).where(
                KnowledgeIndex.id == index.index_id, KnowledgeIndex.owner_id == owner.owner_id,
                KnowledgeIndex.assistant_id == assistant_id))
            chunks = session.scalars(select(KnowledgeChunk).where(
                KnowledgeChunk.index_id == index.index_id,
                KnowledgeChunk.owner_id == owner.owner_id,
                KnowledgeChunk.assistant_id == assistant_id)).all()
            batch = session.scalar(select(KnowledgeIndexBatch).where(
                KnowledgeIndexBatch.index_id == index.index_id,
                KnowledgeIndexBatch.owner_id == owner.owner_id))
            require(assistant is not None and assistant.active_knowledge_index_id == index.index_id,
                    "Active index pointer is missing or belongs to another index")
            require(index_row is not None and index_row.state == "ready",
                    "Persisted index state is not ready")
            require(len(chunks) == 1 and len(chunks[0].embedding) == 768,
                    "Persisted chunk count or embedding dimension mismatch")
            require(all(math.isfinite(float(x)) for x in chunks[0].embedding)
                    and math.hypot(*chunks[0].embedding) > 0,
                    "Persisted embedding is not a finite nonzero vector")
            require(batch is not None and batch.state == "completed"
                    and batch.actual_tokens is not None,
                    "Provider usage was not persisted on the completed batch")
            actual_tokens = batch.actual_tokens

        # Verify the same rows disappear under a different transaction-local owner.
        other_owner = uuid4()
        with sessions.begin() as session:
            set_owner_identity(session, other_owner)
            hidden_index = session.scalar(select(KnowledgeIndex.id).where(
                KnowledgeIndex.id == index.index_id))
            hidden_chunks = session.scalar(select(KnowledgeChunk.id).where(
                KnowledgeChunk.index_id == index.index_id))
            require(hidden_index is None and hidden_chunks is None,
                    "Cross-owner RLS isolation check failed")

        estimated_usd = actual_tokens * 0.02 / 1_000_000
        print("PASS: authenticated owner created one assistant and uploaded one synthetic DOCX")
        print("PASS: one chunk indexed; active pointer references the ready index")
        print("PASS: embedding is 768-dimensional, finite, and nonzero")
        print("PASS: a different owner identity cannot read the test index or chunk")
        print(f"Index ID: {index.index_id}; assistant ID: {assistant_id}; file ID: {file_id}")
        print(f"Index status: {result.state}; chunks: 1; provider tokens: {actual_tokens}")
        print(f"Reserved ceiling for this index: ${reserved / 1_000_000:.6f}")
        print(f"Estimated embedding charge at $0.02/1M tokens: ${estimated_usd:.8f}")
        print("Test assistant and file are retained; no cleanup or provider retries were performed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as exc:
        # Do not print tracebacks, credentials, provider response bodies, or text.
        print("STOP: live indexing verification failed; no automatic retry or cleanup. Error type:",
              type(exc).__name__)
        raise SystemExit(1) from None
