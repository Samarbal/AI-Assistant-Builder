"""One-turn RAG orchestration. No HTTP routes, history, or provider routing."""
from dataclasses import dataclass, field
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .db import set_owner_identity
from .generation import (
    Answer, AnswerGenerator, Behavior, Citation, Evidence, GenerationFailure, SYSTEM, Usage,
    _input_limit_diagnostic, answer_from_evidence,
)
from .models import Assistant
from .retrieval import (
    MAX_RETRIEVAL_TOP_K, RetrievalFailure, RetrievalResult, RetrievedChunk, Retriever,
)


# Keep these packing limits aligned with GroqAnswerGenerator's fail-safe guards.
# The adapter remains authoritative and still rejects any input that exceeds them.
_GENERATION_QUESTION_BYTES = 1000
_GENERATION_EVIDENCE_BYTES = 3000
_GENERATION_PROMPT_BYTES = 6000
_GENERATION_FRAMING_RESERVE_BYTES = 512


def _generation_budget_guard(behavior: Behavior, question: str,
                             evidence: tuple[Evidence, ...]) -> tuple[str | None, dict[str, int]]:
    """Mirror provider guards and return content-free measurements for diagnostics."""
    size = lambda text: len(text.encode("utf-8"))
    question_bytes = size(question) if isinstance(question, str) else 0
    evidence_texts = tuple(item.text for item in evidence
                           if isinstance(item, Evidence) and isinstance(item.text, str))
    top_chunk_bytes = size(evidence_texts[0]) if evidence_texts else 0
    evidence_bytes = sum(size(text) for text in evidence_texts)
    assembled_prompt_bytes = 0
    if (isinstance(question, str) and all(isinstance(value, str) for value in
            (behavior.role, behavior.tone, behavior.response_style))
            and len(evidence_texts) == len(evidence)):
        content = json.dumps({"question": question, "evidence": [
            {"chunk_id": str(item.chunk_id), "text": item.text} for item in evidence]}, ensure_ascii=False)
        instructions = SYSTEM + "\nAssistant behavior: " + json.dumps({
            "role": behavior.role, "tone": behavior.tone, "style": behavior.response_style}, ensure_ascii=False)
        assembled_prompt_bytes = size(content) + size(instructions)

    measurements = {
        "question_bytes": question_bytes,
        "top_chunk_bytes": top_chunk_bytes,
        "evidence_bytes": evidence_bytes,
        "assembled_prompt_bytes": assembled_prompt_bytes,
    }
    if (not evidence or len(evidence) > MAX_RETRIEVAL_TOP_K
            or not question.strip() or len(question) > 4000
            or len({item.chunk_id for item in evidence}) != len(evidence)):
        return "request_shape", measurements
    if question_bytes > _GENERATION_QUESTION_BYTES:
        return "question_bytes", measurements
    if evidence_bytes > _GENERATION_EVIDENCE_BYTES:
        return "evidence_bytes", measurements
    if assembled_prompt_bytes + _GENERATION_FRAMING_RESERVE_BYTES > _GENERATION_PROMPT_BYTES:
        return "assembled_prompt_bytes", measurements
    return None, measurements


def _fits_generation_budget(behavior: Behavior, question: str,
                            evidence: tuple[Evidence, ...]) -> bool:
    """Mirror the provider's current input guards using its exact prompt format."""
    guard, _ = _generation_budget_guard(behavior, question, evidence)
    return guard is None


def _pack_evidence(behavior: Behavior, question: str,
                   evidence: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
    """Select whole chunks greedily in retrieval rank order; never truncate text."""
    top_candidate = (evidence[0],) if evidence else ()
    guard, measurements = _generation_budget_guard(behavior, question, top_candidate)
    if guard is not None:
        _input_limit_diagnostic(
            "rag_packing", f"top_chunk_{guard}", **measurements,
            limits={
                "max_evidence_items": MAX_RETRIEVAL_TOP_K,
                "max_question_chars": 4000,
                "max_question_bytes": _GENERATION_QUESTION_BYTES,
                "max_evidence_bytes": _GENERATION_EVIDENCE_BYTES,
                "max_assembled_prompt_bytes": _GENERATION_PROMPT_BYTES,
                "framing_reserve_bytes": _GENERATION_FRAMING_RESERVE_BYTES,
            },
        )
        raise RagFailure("generation_input_limit", behavior.fallback_message)

    selected = [evidence[0]]
    for item in evidence[1:]:
        candidate = (*selected, item)
        if _fits_generation_budget(behavior, question, candidate):
            selected.append(item)
    return tuple(selected)


class RagFailure(Exception):
    """Stable safe failure; fallback is included only after owner config is known."""

    def __init__(self, code: str, fallback_message: str | None = None):
        self.code = code
        self.fallback_message = fallback_message
        super().__init__(code)


@dataclass(frozen=True)
class _AssistantSnapshot:
    behavior: Behavior
    owner_id: UUID
    assistant_id: UUID
    active_index_id: UUID | None
    configuration_fingerprint: str = field(repr=False)


def _snapshot(row: Assistant) -> _AssistantSnapshot:
    behavior = Behavior(row.role, row.tone, row.response_style, row.fallback_message)
    fingerprint = json.dumps({
        "name": row.name,
        "role": row.role,
        "colors": row.colors,
        "response_style": row.response_style,
        "tone": row.tone,
        "fallback_message": row.fallback_message,
        "state": row.state,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _AssistantSnapshot(behavior, row.owner_id, row.id,
                              row.active_knowledge_index_id, fingerprint)


class RagOrchestrator:
    """Coordinates verified owner context, retrieval, generation, and freshness.

    The caller supplies authenticated owner identity. This class never accepts an
    owner ID from a user message or delegates data access to the text generator.
    """

    def __init__(self, sessions, retriever: Retriever, generator: AnswerGenerator):
        self.sessions = sessions
        self.retriever = retriever
        self.generator = generator

    @staticmethod
    def _set_owner(session, owner_id: UUID) -> None:
        if session.bind.dialect.name == "postgresql":
            set_owner_identity(session, owner_id)

    def _load_snapshot(self, owner_id: UUID, assistant_id: UUID) -> _AssistantSnapshot:
        try:
            with self.sessions.begin() as session:
                self._set_owner(session, owner_id)
                row = session.scalar(select(Assistant).where(
                    Assistant.owner_id == owner_id, Assistant.id == assistant_id))
                if row is None:
                    raise RagFailure("assistant_not_found")
                return _snapshot(row)
        except RagFailure:
            raise
        except SQLAlchemyError:
            raise RagFailure("rag_unavailable") from None

    def _assert_current(self, expected: _AssistantSnapshot, *, index_id: UUID | None) -> None:
        current = self._load_snapshot(expected.owner_id, expected.assistant_id)
        if (current.configuration_fingerprint != expected.configuration_fingerprint
                or current.active_index_id != index_id):
            raise RagFailure("draft_changed", expected.behavior.fallback_message)

    @staticmethod
    def _evidence(chunks: tuple[RetrievedChunk, ...]) -> tuple[Evidence, ...]:
        if not chunks or len(chunks) > MAX_RETRIEVAL_TOP_K:
            raise RagFailure("retrieval_invalid_output")
        try:
            evidence = tuple(Evidence(chunk.file_id, chunk.chunk_id, chunk.filename, chunk.text)
                             for chunk in chunks)
            if (len({item.chunk_id for item in evidence}) != len(evidence)
                    or any(not item.text.strip() or not item.filename for item in evidence)):
                raise ValueError()
            return evidence
        except (AttributeError, TypeError, ValueError):
            raise RagFailure("retrieval_invalid_output") from None

    @staticmethod
    def _validate_answer(answer: Answer, evidence: tuple[Evidence, ...],
                         behavior: Behavior) -> None:
        if (not isinstance(answer, Answer) or answer.outcome not in {"grounded", "fallback"}
                or not isinstance(answer.answer, str) or not isinstance(answer.citations, tuple)):
            raise RagFailure("generation_invalid_output")
        if answer.outcome == "fallback":
            if answer.answer != behavior.fallback_message or answer.citations:
                raise RagFailure("generation_invalid_output")
        elif not answer.answer.strip():
            raise RagFailure("generation_invalid_output")
        available = {item.chunk_id: item for item in evidence}
        citations = answer.citations
        if ((answer.outcome == "grounded" and not citations)
                or len(citations) > MAX_RETRIEVAL_TOP_K):
            raise RagFailure("generation_invalid_output")
        seen = set()
        for citation in citations:
            if (not isinstance(citation, Citation) or not isinstance(citation.excerpt, str)
                    or not isinstance(citation.filename, str)):
                raise RagFailure("generation_invalid_output")
            source = available.get(citation.chunk_id)
            if (source is None or citation.chunk_id in seen or citation.file_id != source.file_id
                    or citation.filename != source.filename or not citation.excerpt.strip()
                    or citation.excerpt not in source.text):
                raise RagFailure("generation_invalid_output")
            seen.add(citation.chunk_id)
        usage = answer.usage
        if usage is not None and (
            not isinstance(usage, Usage)
            or any(type(value) is not int or value < 0 for value in
                   (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens))
            or usage.prompt_tokens > 6000 or usage.completion_tokens > 512
            or usage.total_tokens != usage.prompt_tokens + usage.completion_tokens
        ):
            raise RagFailure("generation_invalid_output")

    async def answer(self, owner_id: UUID, assistant_id: UUID, question: str) -> Answer:
        if (not isinstance(owner_id, UUID) or not isinstance(assistant_id, UUID)
                or not isinstance(question, str) or not question.strip() or len(question) > 4000):
            raise RagFailure("rag_invalid_request")
        snapshot = self._load_snapshot(owner_id, assistant_id)
        try:
            result = await self.retriever.retrieve(owner_id, assistant_id, question,
                                                   top_k=MAX_RETRIEVAL_TOP_K)
        except RetrievalFailure as exc:
            raise RagFailure(exc.code, snapshot.behavior.fallback_message) from None
        except Exception:
            raise RagFailure("retrieval_unavailable", snapshot.behavior.fallback_message) from None

        if not isinstance(result, RetrievalResult):
            raise RagFailure("retrieval_invalid_output", snapshot.behavior.fallback_message)
        if result.state in {"needs_preparation", "knowledge_not_ready"}:
            raise RagFailure("knowledge_not_ready", snapshot.behavior.fallback_message)
        if result.state == "no_knowledge":
            self._assert_current(snapshot, index_id=None)
            return await answer_from_evidence(self.generator, snapshot.behavior, question, ())
        if result.state == "no_relevant_chunks":
            self._assert_current(snapshot, index_id=result.index_id)
            return await answer_from_evidence(self.generator, snapshot.behavior, question, ())
        if result.state != "matches" or result.index_id is None:
            raise RagFailure("retrieval_invalid_output", snapshot.behavior.fallback_message)
        if snapshot.active_index_id != result.index_id:
            raise RagFailure("knowledge_not_ready", snapshot.behavior.fallback_message)

        evidence = self._evidence(result.chunks)
        evidence = _pack_evidence(snapshot.behavior, question, evidence)
        # Avoid paying for generation if the draft/index changed after retrieval.
        self._assert_current(snapshot, index_id=result.index_id)
        try:
            answer = await answer_from_evidence(self.generator, snapshot.behavior, question, evidence)
        except GenerationFailure as exc:
            raise RagFailure(exc.code, snapshot.behavior.fallback_message) from None
        except Exception:
            raise RagFailure("generation_unavailable", snapshot.behavior.fallback_message) from None
        try:
            self._validate_answer(answer, evidence, snapshot.behavior)
        except RagFailure as exc:
            raise RagFailure(exc.code, snapshot.behavior.fallback_message) from None
        # A configuration or source change during generation invalidates answer
        # and citations; the caller may explicitly retry against the new draft.
        self._assert_current(snapshot, index_id=result.index_id)
        return answer
