"""Gated public chat over immutable published snapshots.

Demo access is disabled unless explicitly enabled and configured with at most two
SHA-256 hashed access tokens. Visitor capabilities are returned once and only
their digest is stored. No owner/draft tables are read through the public role.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections import OrderedDict, deque
from dataclasses import dataclass
from hashlib import sha256
import hmac
import secrets
import time
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .generation import Answer, AnswerGenerator, Behavior, Evidence, GenerationFailure, answer_from_evidence
from .rag import RagOrchestrator, RagFailure, _pack_evidence
from .retrieval import MAX_RETRIEVAL_TOP_K


class PublicChatFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class PublicEmbedding(Protocol):
    model: str
    dimension: int
    async def embed(self, texts: tuple[str, ...]): ...


@dataclass(frozen=True)
class PublicAssistant:
    publication_id: UUID
    public_id: UUID
    assistant_id: UUID
    owner_id: UUID
    snapshot_id: UUID
    version: int
    config: dict
    knowledge_index_id: UUID | None
    embedding_provider: str | None
    embedding_model: str | None
    vector_dimension: int | None
    minimum_similarity: float | None
    source_count: int


_PUBLIC_RETRIEVAL_SQL = text("""
SELECT c.file_id,c.id chunk_id,c.chunk_text,
       1 - (c.embedding <=> CAST(:query_vector AS public.vector(768))) similarity
  FROM public.published_sources r
  JOIN public.knowledge_chunks c ON c.index_id=r.index_id AND c.file_id=r.file_id
    AND c.assistant_id=r.assistant_id AND c.owner_id=r.owner_id
 WHERE r.snapshot_id=:snapshot_id AND r.index_id=:index_id
   AND c.extraction_version=r.extraction_version AND c.source_sha256=r.source_sha256
   AND 1 - (c.embedding <=> CAST(:query_vector AS public.vector(768))) >= :threshold
 ORDER BY c.embedding <=> CAST(:query_vector AS public.vector(768)),c.id
 LIMIT :top_k
""")


def _set_public_context(session, *, public_id: UUID, snapshot_id: UUID | None = None,
                        conversation_id: UUID | None = None,
                        token_digest: str | None = None) -> None:
    # Always write every RLS context value transaction-locally, including empty
    # values, to prevent pooled connection context reuse.
    values = {
        "app.public_id": str(public_id),
        "app.snapshot_id": str(snapshot_id) if snapshot_id else "",
        "app.conversation_id": str(conversation_id) if conversation_id else "",
        "app.visitor_token_digest": token_digest or "",
    }
    for key, value in values.items():
        session.execute(text("SELECT set_config(:key,:value,true)"), {"key": key, "value": value})


class PublicDemoGate:
    """Constant-time validation for one or two operator-provisioned demo tokens."""
    def __init__(self, enabled: bool, configured_hashes: str | None):
        hashes = tuple(item.strip().lower() for item in (configured_hashes or "").split(",") if item.strip())
        if len(hashes) > 2 or any(len(item) != 64 or any(c not in "0123456789abcdef" for c in item) for item in hashes):
            raise ValueError("Public demo gate configuration is invalid")
        self.enabled = enabled
        self._hashes = hashes

    def check(self, token: str | None) -> None:
        if not self.enabled or not self._hashes:
            raise PublicChatFailure("public_chat_disabled")
        candidate = sha256((token or "").encode("utf-8")).hexdigest()
        if not token or not any(hmac.compare_digest(candidate, expected) for expected in self._hashes):
            raise PublicChatFailure("demo_access_denied")


class PublicRequestGuard:
    """Bounded single-process demo rate/concurrency guard; no proxy IP trust."""
    def __init__(self, *, rate: int = 30, per_assistant: int = 2,
                 global_limit: int = 4, key_capacity: int = 4096, clock=time.monotonic):
        self.rate, self.per_assistant = rate, per_assistant
        self.key_capacity, self.clock = key_capacity, clock
        self._events: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._global = asyncio.Semaphore(global_limit)
        self._assistant: dict[str, asyncio.Semaphore] = {}
        self._conversations: set[str] = set()

    def acquire_conversation(self, conversation_id: UUID) -> None:
        key = str(conversation_id)
        if key in self._conversations:
            raise PublicChatFailure("request_in_progress")
        if len(self._conversations) >= self.key_capacity:
            raise PublicChatFailure("rate_limited")
        self._conversations.add(key)

    def release_conversation(self, conversation_id: UUID) -> None:
        self._conversations.discard(str(conversation_id))

    async def check_rate(self, ip: str, public_id: UUID):
        key = (ip, str(public_id))
        async with self._lock:
            now = self.clock()
            events = self._events.get(key)
            if events is None:
                if len(self._events) >= self.key_capacity:
                    raise PublicChatFailure("rate_limited")
                events = self._events[key] = deque()
            else:
                self._events.move_to_end(key)
            while events and now - events[0] >= 60:
                events.popleft()
            if len(events) >= self.rate:
                raise PublicChatFailure("rate_limited")
            events.append(now)

    @asynccontextmanager
    async def slot(self, public_id: UUID):
        key = str(public_id)
        if key not in self._assistant:
            if len(self._assistant) >= self.key_capacity:
                raise PublicChatFailure("rate_limited")
            self._assistant[key] = asyncio.Semaphore(self.per_assistant)
        local = self._assistant[key]
        if self._global.locked() or local.locked():
            raise PublicChatFailure("concurrency_limited")
        await self._global.acquire()
        if local.locked():
            self._global.release()
            raise PublicChatFailure("concurrency_limited")
        await local.acquire()
        try:
            yield
        finally:
            local.release()
            self._global.release()


class PublicChatService:
    def __init__(self, sessions, embeddings: PublicEmbedding, generator: AnswerGenerator,
                 guard: PublicRequestGuard):
        self.sessions, self.embeddings, self.generator, self.guard = sessions, embeddings, generator, guard

    @staticmethod
    def _assistant(row) -> PublicAssistant:
        if row is None:
            raise PublicChatFailure("assistant_unavailable")
        return PublicAssistant(**dict(row))

    def _load_assistant(self, public_id: UUID, snapshot_id: UUID | None = None) -> PublicAssistant:
        try:
            with self.sessions.begin() as session:
                _set_public_context(session, public_id=public_id)
                mapping = session.execute(text("""SELECT id publication_id,public_id,assistant_id,
                    owner_id,active_snapshot_id FROM public.assistant_publications
                    WHERE public_id=:public_id AND active_snapshot_id IS NOT NULL"""),
                    {"public_id": public_id}).mappings().one_or_none()
                if mapping is None:
                    return self._assistant(None)
                expected_snapshot = snapshot_id or mapping["active_snapshot_id"]
                if expected_snapshot != mapping["active_snapshot_id"]:
                    return self._assistant(None)
                _set_public_context(session, public_id=public_id, snapshot_id=expected_snapshot)
                row = session.execute(text("""SELECT :publication_id publication_id,:public_id public_id,
                    :assistant_id assistant_id,:owner_id owner_id,s.id snapshot_id,s.version,s.config,
                    s.knowledge_index_id,s.embedding_provider,s.embedding_model,s.vector_dimension,
                    s.retrieval_min_similarity minimum_similarity,s.source_count
                    FROM public.published_snapshots s WHERE s.id=:snapshot_id AND s.state='published'
                      AND s.assistant_id=:assistant_id AND s.owner_id=:owner_id"""), {
                    "publication_id": mapping["publication_id"], "public_id": public_id,
                    "assistant_id": mapping["assistant_id"], "owner_id": mapping["owner_id"],
                    "snapshot_id": expected_snapshot}).mappings().one_or_none()
                return self._assistant(row)
        except PublicChatFailure:
            raise
        except SQLAlchemyError:
            raise PublicChatFailure("public_unavailable") from None

    def public_details(self, public_id: UUID) -> dict:
        item = self._load_assistant(public_id)
        return {"name": item.config.get("name", "Assistant"),
                "colors": item.config.get("colors", {}), "version": item.version}

    def create_conversation(self, public_id: UUID) -> dict:
        item = self._load_assistant(public_id)
        conversation_id = uuid4()
        token = secrets.token_urlsafe(32)
        digest = sha256(token.encode()).hexdigest()
        try:
            with self.sessions.begin() as session:
                _set_public_context(session, public_id=public_id, snapshot_id=item.snapshot_id,
                    conversation_id=conversation_id, token_digest=digest)
                expires_at = session.execute(text("""
                    INSERT INTO public.visitor_conversations
                      (id,publication_id,assistant_id,owner_id,token_sha256,expires_at)
                    VALUES (:id,:publication_id,:assistant_id,:owner_id,:digest,now()+interval '24 hours')
                    RETURNING expires_at
                """), {"id": conversation_id, "publication_id": item.publication_id,
                    "assistant_id": item.assistant_id, "owner_id": item.owner_id, "digest": digest}).scalar_one()
        except SQLAlchemyError:
            raise PublicChatFailure("public_unavailable") from None
        return {"conversation_id": conversation_id, "conversation_token": token,
                "expires_at": expires_at}

    async def message(self, public_id: UUID, conversation_id: UUID, token: str,
                      message: str, request_id: UUID) -> dict:
        self.guard.acquire_conversation(conversation_id)
        try:
            # Reserve capacity before the durable pending turn is inserted, so a
            # saturated service cannot strand an unstarted request in the ledger.
            async with self.guard.slot(public_id):
                return await self._message_impl(public_id, conversation_id, token, message, request_id)
        finally:
            self.guard.release_conversation(conversation_id)

    async def _message_impl(self, public_id: UUID, conversation_id: UUID, token: str,
                            message: str, request_id: UUID) -> dict:
        if not isinstance(message, str) or not message.strip() or len(message.encode("utf-8")) > 1000:
            raise PublicChatFailure("invalid_request")
        if len(token) > 256 or not token:
            raise PublicChatFailure("conversation_unavailable")
        token_digest = sha256(token.encode()).hexdigest()
        input_digest = sha256(message.encode("utf-8")).hexdigest()
        version_rejected = False
        response = None
        try:
            with self.sessions.begin() as session:
                _set_public_context(session, public_id=public_id, conversation_id=conversation_id,
                                    token_digest=token_digest)
                conversation = session.execute(text("""
                    SELECT id,publication_id,assistant_id,owner_id,expires_at
                      FROM public.visitor_conversations
                     WHERE id=:id AND expires_at>now()
                """), {"id": conversation_id}).mappings().one_or_none()
                if conversation is None:
                    raise PublicChatFailure("conversation_unavailable")
                item = self._load_assistant(public_id)
                prior = session.execute(text("""
                    SELECT id,request_id,input_sha256,snapshot_id,state,answer_text,outcome,created_at
                      FROM public.visitor_turns WHERE conversation_id=:id AND request_id=:request_id
                """), {"id": conversation_id, "request_id": request_id}).mappings().one_or_none()
                if prior is not None:
                    if prior["input_sha256"] != input_digest:
                        raise PublicChatFailure("request_conflict")
                    if prior["state"] not in {"completed", "fallback"} or prior["snapshot_id"] != item.snapshot_id:
                        raise PublicChatFailure("request_in_progress" if prior["state"] == "pending" else "published_version_changed")
                    return {"message_id": prior["id"], "answer": prior["answer_text"],
                            "outcome": prior["outcome"], "created_at": prior["created_at"], "version": item.version}
                _set_public_context(session, public_id=public_id, snapshot_id=item.snapshot_id,
                                    conversation_id=conversation_id, token_digest=token_digest)
                turn_id = uuid4()
                session.execute(text("""
                    INSERT INTO public.visitor_turns
                      (id,conversation_id,publication_id,snapshot_id,assistant_id,owner_id,request_id,
                       input_sha256,user_text,state)
                    VALUES (:id,:conversation_id,:publication_id,:snapshot_id,:assistant_id,:owner_id,
                       :request_id,:input_sha256,:user_text,'pending')
                """), {"id": turn_id, "conversation_id": conversation_id,
                    "publication_id": conversation["publication_id"], "snapshot_id": item.snapshot_id,
                    "assistant_id": conversation["assistant_id"], "owner_id": conversation["owner_id"],
                    "request_id": request_id, "input_sha256": input_digest, "user_text": message})
                session.flush()
        except PublicChatFailure:
            raise
        except IntegrityError:
            raise PublicChatFailure("request_in_progress") from None
        except SQLAlchemyError:
            raise PublicChatFailure("public_unavailable") from None

        try:
            answer = await self._answer(item, message)
        except (TimeoutError, PublicChatFailure) as exc:
            code = exc.code if isinstance(exc, PublicChatFailure) else "public_timeout"
            state = "failed" if code == "knowledge_not_ready" else "uncertain"
            await self._fail_turn(public_id, item, conversation_id, token_digest, turn_id, code, state=state)
            raise PublicChatFailure(code) from None
        except Exception:
            await self._fail_turn(public_id, item, conversation_id, token_digest, turn_id,
                                  "public_provider_failure", state="uncertain")
            raise PublicChatFailure("public_provider_failure") from None
        return self._finalize(public_id, item, conversation_id, token_digest, turn_id, answer)

    async def _answer(self, item: PublicAssistant, question: str) -> Answer:
        behavior = Behavior(item.config["role"], item.config["tone"],
                            item.config["response_style"], item.config["fallback_message"])
        if item.source_count == 0:
            return Answer(behavior.fallback_message, "fallback")
        if (item.knowledge_index_id is None or item.embedding_model != self.embeddings.model
                or item.vector_dimension != self.embeddings.dimension
                or not isinstance(item.minimum_similarity, (int, float))):
            raise PublicChatFailure("knowledge_not_ready")
        try:
            embedded = await self.embeddings.embed((question,))
        except Exception:
            raise PublicChatFailure("public_provider_failure") from None
        if (embedded.model != item.embedding_model or embedded.dimensions != item.vector_dimension
                or len(embedded.vectors) != 1 or len(embedded.vectors[0]) != item.vector_dimension):
            raise PublicChatFailure("public_provider_failure")
        import math
        vector = embedded.vectors[0]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in vector) or math.hypot(*vector) == 0:
            raise PublicChatFailure("public_provider_failure")
        vector_literal = "[" + ",".join(repr(float(value)) for value in vector) + "]"
        try:
            with self.sessions.begin() as session:
                _set_public_context(session, public_id=item.public_id, snapshot_id=item.snapshot_id)
                rows = session.execute(_PUBLIC_RETRIEVAL_SQL, {
                    "snapshot_id": item.snapshot_id, "index_id": item.knowledge_index_id,
                    "query_vector": vector_literal, "threshold": item.minimum_similarity,
                    "top_k": MAX_RETRIEVAL_TOP_K,
                }).mappings().all()
        except SQLAlchemyError:
            raise PublicChatFailure("public_unavailable") from None
        if not rows:
            return Answer(behavior.fallback_message, "fallback")
        evidence = tuple(Evidence(row["file_id"], row["chunk_id"], "Published knowledge", row["chunk_text"])
                         for row in rows)
        try:
            evidence = _pack_evidence(behavior, question, evidence)
            answer = await answer_from_evidence(self.generator, behavior, question, evidence)
            RagOrchestrator._validate_answer(answer, evidence, behavior)
            return answer
        except (RagFailure, GenerationFailure):
            raise PublicChatFailure("public_provider_failure") from None

    async def _fail_turn(self, public_id, item, conversation_id, token_digest, turn_id, code, *, state):
        try:
            with self.sessions.begin() as session:
                _set_public_context(session, public_id=public_id, snapshot_id=item.snapshot_id,
                    conversation_id=conversation_id, token_digest=token_digest)
                session.execute(text("""UPDATE public.visitor_turns SET state=:state,error_code=:code,
                    completed_at=now() WHERE id=:id AND state='pending'"""),
                    {"id": turn_id, "code": code, "state": state})
        except SQLAlchemyError:
            # Unknown persistence outcome must not trigger automatic provider replay.
            return

    def _finalize(self, public_id, item, conversation_id, token_digest, turn_id, answer):
        from sqlalchemy import text as sql_text
        version_rejected = False
        response = None
        try:
            with self.sessions.begin() as session:
                _set_public_context(session, public_id=public_id, snapshot_id=item.snapshot_id,
                    conversation_id=conversation_id, token_digest=token_digest)
                session.execute(sql_text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                                {"key": f"publish:{item.assistant_id}"})
                active = session.execute(sql_text("""SELECT active_snapshot_id FROM public.assistant_publications
                    WHERE id=:id"""), {"id": item.publication_id}).scalar_one_or_none()
                if active != item.snapshot_id:
                    session.execute(sql_text("""UPDATE public.visitor_turns SET state='version_rejected',
                        error_code='published_version_changed',completed_at=now()
                        WHERE id=:id AND state='pending'"""), {"id": turn_id})
                    version_rejected = True
                else:
                    final_state = "fallback" if answer.outcome == "fallback" else "completed"
                    row = session.execute(sql_text("""UPDATE public.visitor_turns SET state=:state,
                        answer_text=:answer,outcome=:outcome,completed_at=now()
                        WHERE id=:id AND state='pending' RETURNING id,answer_text,outcome,created_at"""),
                        {"state": final_state, "answer": answer.answer, "outcome": answer.outcome,
                         "id": turn_id}).mappings().one_or_none()
                    if row is None:
                        raise PublicChatFailure("request_in_progress")
                    response = {"message_id": row["id"], "answer": row["answer_text"],
                                "outcome": row["outcome"], "created_at": row["created_at"], "version": item.version}
        except PublicChatFailure:
            raise
        except SQLAlchemyError:
            raise PublicChatFailure("public_unavailable") from None
        if version_rejected:
            raise PublicChatFailure("published_version_changed")
        return response
