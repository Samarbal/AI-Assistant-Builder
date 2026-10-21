"""Run one authenticated, synthetic-only Playground smoke test.

The script is read-only: it signs in a dedicated owner, verifies that the
specified assistant is theirs and has a ready active index containing the
known synthetic fixture, then sends one question through the Playground API.
It creates no database or Storage records and never prints secrets or text.
"""
import getpass
import logging
import re
import sys
import warnings
from uuid import UUID, uuid4

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from assistant_builder.auth import SupabaseAuthVerifier
from assistant_builder.config import Settings
from assistant_builder.db import set_owner_identity
from assistant_builder.main import create_app
from assistant_builder.models import Assistant, KnowledgeChunk, KnowledgeIndex


SYNTHETIC_FIXTURE = "The fictional demo code word is maple."
QUESTION = "What is the fictional demo code word?"
CURRENT_STAGE = "startup"
SAFE_API_CODES = {
    "assistant_not_found", "knowledge_not_ready", "draft_changed", "rag_invalid_request",
    "playground_unavailable", "rag_unavailable", "retrieval_unavailable",
    "retrieval_invalid_output", "retrieval_configuration", "embedding_unavailable",
    "embedding_space_mismatch", "embedding_invalid_output", "embedding_configuration",
    "embedding_input_limit", "embedding_auth", "embedding_quota_or_rate_limited",
    "embedding_model_unavailable", "embedding_timeout", "generation_configuration",
    "generation_input_limit", "generation_auth", "generation_rate_limited",
    "generation_model_unavailable", "generation_timeout", "generation_unavailable",
    "generation_invalid_output", "generation_output_invalid_json",
    "generation_output_invalid_envelope", "generation_output_invalid_usage",
    "generation_output_incomplete", "generation_output_refused",
    "generation_output_invalid_schema", "generation_output_invalid_citation",
    "generation_output_too_large",
}


class SafeVerificationFailure(Exception):
    def __init__(self, stage: str, code: str):
        self.stage = stage
        self.code = code
        super().__init__(code)


def set_stage(stage: str) -> None:
    global CURRENT_STAGE
    CURRENT_STAGE = stage


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SafeVerificationFailure(CURRENT_STAGE, message)


def api_failure_code(response) -> str:
    """Return only an allowlisted API code, never response text or details."""
    try:
        detail = response.json().get("detail")
        candidate = detail.get("code") if isinstance(detail, dict) else None
    except (ValueError, AttributeError, TypeError):
        candidate = None
    return candidate if isinstance(candidate, str) and candidate in SAFE_API_CODES else "unknown"


def validate_settings(settings: Settings) -> None:
    from signin_phase1 import validate_auth_settings

    set_stage("configuration")
    validate_auth_settings(settings)
    required = (
        settings.database_url,
        settings.ai_base_url,
        settings.ai_api_key,
        settings.ai_model,
        settings.embedding_base_url,
        settings.embedding_api_key,
        settings.embedding_model,
        settings.retrieval_min_similarity,
    )
    require(all(required), "Required database, provider, or retrieval configuration is missing")
    require(settings.ai_model == "openai/gpt-oss-20b", "Generation model differs from validated candidate")
    require(settings.embedding_model == "text-embedding-3-small", "Embedding model differs from validated candidate")
    require(settings.embedding_dimension == 768, "Embedding dimension must be 768")
    require(settings.ai_base_url is not None and "groq" in settings.ai_base_url.lower(),
            "Generation endpoint is not the approved Groq endpoint")
    require(settings.embedding_base_url is not None and "openai" in settings.embedding_base_url.lower(),
            "Embedding endpoint is not the approved OpenAI endpoint")
    require(settings.ai_timeout_seconds <= 12 and settings.embedding_timeout_seconds <= 12,
            "Provider deadline exceeds the approved 12-second bound")
    require(settings.embedding_max_batch_size <= 8 and settings.embedding_max_input_tokens <= 4800,
            "Embedding request bounds exceed approved limits")


def main() -> int:
    set_stage("startup")
    logging.disable(logging.CRITICAL)
    warnings.filterwarnings("error", category=getpass.GetPassWarning)
    if not sys.stdin.isatty():
        print("STOP: run this script from an interactive terminal; password input must be hidden")
        return 2

    settings = Settings()
    validate_settings(settings)
    set_stage("assistant_selection")
    assistant_raw = input("Existing indexed synthetic assistant UUID: ").strip()
    try:
        assistant_id = UUID(assistant_raw)
    except ValueError:
        print("STOP: assistant UUID is invalid")
        return 2
    email = input("Dedicated test owner email: ").strip()
    password = getpass.getpass("Test owner password (hidden): ")

    set_stage("owner_authentication")
    from signin_phase1 import sign_in

    with httpx.Client(timeout=20, follow_redirects=False) as auth_client:
        token = sign_in(auth_client, settings.supabase_url, settings.supabase_anon_key, email, password)
        del email, password
        owner = SupabaseAuthVerifier(settings.supabase_url, settings.supabase_anon_key,
                                     auth_client).verify("Bearer " + token)

    app = create_app()
    set_stage("runtime_database_startup")
    with TestClient(app) as client:
        sessions = app.state.session_factory
        require(sessions is not None, "Runtime database session factory is unavailable")
        set_stage("assistant_ownership_and_index_readiness")
        with sessions.begin() as session:
            set_owner_identity(session, owner.owner_id)
            assistant = session.scalar(select(Assistant).where(
                Assistant.id == assistant_id, Assistant.owner_id == owner.owner_id))
            require(assistant is not None, "Assistant is not owned by the authenticated test user")
            index_id = assistant.active_knowledge_index_id
            require(index_id is not None, "Assistant has no active knowledge index")
            index = session.scalar(select(KnowledgeIndex).where(
                KnowledgeIndex.id == index_id,
                KnowledgeIndex.assistant_id == assistant_id,
                KnowledgeIndex.owner_id == owner.owner_id))
            require(index is not None and index.state == "ready",
                    "Assistant active index is not ready")
            require(index.embedding_provider == "openai"
                    and index.embedding_model == settings.embedding_model
                    and index.vector_dimension == 768,
                    "Active index embedding space does not match configured provider/model/dimension")
            fixture_count = session.scalar(select(KnowledgeChunk.id).where(
                KnowledgeChunk.index_id == index_id,
                KnowledgeChunk.owner_id == owner.owner_id,
                KnowledgeChunk.assistant_id == assistant_id,
                KnowledgeChunk.chunk_text.contains(SYNTHETIC_FIXTURE)).limit(1))
            require(fixture_count is not None,
                    "Active index does not contain the expected synthetic demo fixture")

        # Fail-closed owner-isolation precheck under a different transaction identity.
        set_stage("owner_isolation_precheck")
        with sessions.begin() as session:
            set_owner_identity(session, uuid4())
            hidden = session.scalar(select(KnowledgeIndex.id).where(KnowledgeIndex.id == index_id))
            require(hidden is None, "A different owner identity can see the active index")

        set_stage("playground_embedding_retrieval_generation")
        response = client.post(
            f"/assistants/{assistant_id}/playground/messages",
            headers={"Authorization": "Bearer " + token},
            json={"message": QUESTION},
        )
        if response.status_code != 200:
            raise SafeVerificationFailure(
                CURRENT_STAGE, f"http_{response.status_code}_{api_failure_code(response)}")
        result = response.json()
        set_stage("grounded_answer_and_citation_validation")
        require(result.get("outcome") == "grounded", "Expected a grounded answer")
        require("maple" in result.get("answer", "").lower(),
                "Grounded answer did not include the synthetic expected fact")
        citations = result.get("citations")
        require(isinstance(citations, list) and len(citations) >= 1,
                "Grounded answer did not return a validated citation")
        require(all(item.get("chunk_id") and item.get("file_id") and item.get("filename")
                    and item.get("excerpt") for item in citations),
                "Citation metadata is incomplete")

    print("PASS: authenticated owner owns the selected assistant and ready active index")
    print("PASS: a different transaction-local owner cannot see the active index")
    print("PASS: one Playground request completed retrieval and grounded Groq generation")
    print(f"PASS: synthetic expected fact verified; citations={len(citations)}; no text or secrets printed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SafeVerificationFailure as exc:
        print(f"STOP: live verification failed at stage={exc.stage}; code={exc.code}. No retries or writes.")
        raise SystemExit(1) from None
    except (Exception, KeyboardInterrupt) as exc:
        safe_type = type(exc).__name__
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", safe_type):
            safe_type = "UnexpectedError"
        print(f"STOP: live verification failed at stage={CURRENT_STAGE}; code=unexpected_{safe_type}. No retries or writes.")
        raise SystemExit(1) from None
