import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from assistant_builder.generation import (
    Answer, Behavior, Citation, GenerationFailure, Usage,
)
from assistant_builder.models import Assistant, Base
from assistant_builder.rag import RagFailure, RagOrchestrator
from assistant_builder.retrieval import RetrievalFailure, RetrievalResult, RetrievedChunk
from .test_phase1_contracts import payload


@pytest.fixture
def database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    owner, other = uuid4(), uuid4()
    assistant = Assistant(owner_id=owner, **payload())
    other_assistant = Assistant(owner_id=other, **payload())
    with sessions.begin() as session:
        session.add_all((assistant, other_assistant))
        session.flush()
        ids = assistant.id, other_assistant.id
    yield sessions, owner, other, ids
    engine.dispose()


class FakeRetriever:
    def __init__(self, result=None, failure=None, before_return=None):
        self.result, self.failure, self.before_return = result, failure, before_return
        self.calls = []

    async def retrieve(self, owner, assistant, query, *, top_k):
        self.calls.append((owner, assistant, query, top_k))
        if self.before_return:
            self.before_return()
        if self.failure:
            raise self.failure
        return self.result


class FakeGenerator:
    def __init__(self, failure=None, answer_factory=None, during_call=None):
        self.failure, self.answer_factory, self.during_call = failure, answer_factory, during_call
        self.calls = []

    async def generate(self, behavior, question, evidence):
        self.calls.append((behavior, question, evidence))
        if self.during_call:
            self.during_call()
        if self.failure:
            raise self.failure
        if self.answer_factory:
            return self.answer_factory(evidence)
        source = evidence[0]
        return Answer("Returns are accepted within 14 days.", "grounded", (
            Citation(source.file_id, source.chunk_id, source.filename,
                     "Returns are accepted within 14 days."),
        ), Usage(12, 8, 20))


def chunk(owner_file=None, *, text="Returns are accepted within 14 days.", score=0.91):
    return RetrievedChunk(owner_file or uuid4(), uuid4(), "policy.pdf", text, score,
                          0, len(text), "extract-v1")


def test_grounded_flow_passes_only_server_retrieved_evidence(database):
    sessions, owner, _, ids = database
    index_id = uuid4()
    source = chunk()
    retriever = FakeRetriever(RetrievalResult("matches", (source,), index_id))
    generator = FakeGenerator()
    with sessions.begin() as session:
        row = session.get(Assistant, ids[0])
        row.active_knowledge_index_id = index_id
    orchestrator = RagOrchestrator(sessions, retriever, generator)

    answer = asyncio.run(orchestrator.answer(owner, ids[0], "What is the return policy?"))

    assert answer.outcome == "grounded"
    assert answer.citations[0].chunk_id == source.chunk_id
    assert generator.calls[0][2][0].text == source.text
    assert retriever.calls[0] == (owner, ids[0], "What is the return policy?", 5)


def test_valid_generation_abstention_returns_exact_configured_fallback(database):
    sessions, owner, _, ids = database
    index_id = uuid4()
    source = chunk()
    with sessions.begin() as session:
        assistant = session.get(Assistant, ids[0])
        assistant.active_knowledge_index_id = index_id
        fallback = assistant.fallback_message

    class AbstainingGenerator:
        async def generate(self, behavior, question, evidence):
            assert evidence
            # The real adapter discards this generated string and returns the
            # configured fallback; this fake models that adapter contract.
            return Answer(behavior.fallback_message, "fallback", ())

    orchestrator = RagOrchestrator(
        sessions, FakeRetriever(RetrievalResult("matches", (source,), index_id)),
        AbstainingGenerator())
    answer = asyncio.run(orchestrator.answer(owner, ids[0], "What is unsupported?"))

    assert answer == Answer(fallback, "fallback", ())


def test_rag_rejects_nonconfigured_fallback_from_generator(database):
    sessions, owner, _, ids = database
    index_id = uuid4()
    source = chunk()
    with sessions.begin() as session:
        session.get(Assistant, ids[0]).active_knowledge_index_id = index_id

    class ForgedFallbackGenerator:
        async def generate(self, behavior, question, evidence):
            return Answer("untrusted generated abstention", "fallback", ())

    orchestrator = RagOrchestrator(
        sessions, FakeRetriever(RetrievalResult("matches", (source,), index_id)),
        ForgedFallbackGenerator())
    with pytest.raises(RagFailure, match="generation_invalid_output"):
        asyncio.run(orchestrator.answer(owner, ids[0], "What is unsupported?"))


def _answer_for_first_evidence(evidence):
    source = evidence[0]
    excerpt = source.text[:min(32, len(source.text))]
    return Answer("Supported answer", "grounded", (
        Citation(source.file_id, source.chunk_id, source.filename, excerpt),
    ))


def _run_with_sources(database, sources, *, question="What is supported?", behavior=None):
    sessions, owner, _, ids = database
    index_id = uuid4()
    with sessions.begin() as session:
        assistant = session.get(Assistant, ids[0])
        assistant.active_knowledge_index_id = index_id
        if behavior is not None:
            assistant.role, assistant.tone, assistant.response_style = behavior
    retriever = FakeRetriever(RetrievalResult("matches", tuple(sources), index_id))
    generator = FakeGenerator(answer_factory=_answer_for_first_evidence)
    answer = asyncio.run(RagOrchestrator(sessions, retriever, generator).answer(
        owner, ids[0], question))
    return answer, generator


def test_context_packing_keeps_whole_highest_ranked_chunks_and_skips_oversized_addition(database):
    first = chunk(text="Returns are accepted within 14 days." + "a" * 1960, score=0.99)
    too_large_to_add = chunk(text="b" * 1500, score=0.95)
    third = chunk(text="c" * 150, score=0.90)
    _, generator = _run_with_sources(database, (first, too_large_to_add, third))

    sent = generator.calls[0][2]
    assert [item.chunk_id for item in sent] == [first.chunk_id, third.chunk_id]
    assert sent[0].text == first.text
    assert sent[1].text == third.text


def test_context_packing_uses_utf8_bytes_without_truncating_arabic_chunks(database):
    first = chunk(text="ا" * 1250, score=0.99)  # 2,500 UTF-8 bytes
    second = chunk(text="ب" * 400, score=0.95)  # does not fit after the first
    third = chunk(text="ج" * 100, score=0.90)
    _, generator = _run_with_sources(database, (first, second, third))

    sent = generator.calls[0][2]
    assert [item.chunk_id for item in sent] == [first.chunk_id, third.chunk_id]
    assert sent[0].text == first.text
    assert sent[1].text == third.text


def test_context_packing_fails_without_generation_when_top_chunk_exceeds_evidence_budget(
        database, monkeypatch):
    records = []
    monkeypatch.setattr("assistant_builder.generation.logger.warning",
                        lambda message, *, extra: records.append((message, extra)))
    sessions, owner, _, ids = database
    index_id = uuid4()
    with sessions.begin() as session:
        session.get(Assistant, ids[0]).active_knowledge_index_id = index_id
    source = chunk(text="x" * 3001, score=0.99)
    retriever, generator = FakeRetriever(RetrievalResult("matches", (source,), index_id)), FakeGenerator()

    with pytest.raises(RagFailure) as error:
        asyncio.run(RagOrchestrator(sessions, retriever, generator).answer(owner, ids[0], "question"))

    assert error.value.code == "generation_input_limit"
    assert error.value.fallback_message == sessions().get(Assistant, ids[0]).fallback_message
    assert generator.calls == []
    message, record = records[-1]
    assert message.startswith("generation_input_limit_diagnostic {")
    assert record["input_limit_stage"] == "rag_packing"
    assert record["input_limit_guard"] == "top_chunk_evidence_bytes"
    assert record["question_bytes"] == len(b"question")
    assert record["top_chunk_bytes"] == 3001
    assert record["evidence_bytes"] == 3001
    assert isinstance(record["assembled_prompt_bytes"], int)
    assert record["input_limits"]["max_evidence_bytes"] == 3000
    assert record["input_limits"]["max_assembled_prompt_bytes"] == 6000
    assert source.text not in message + repr(record)
    assert source.filename not in message + repr(record)


def test_context_packing_accounts_for_json_prompt_expansion(database):
    sessions, owner, _, ids = database
    index_id = uuid4()
    with sessions.begin() as session:
        session.get(Assistant, ids[0]).active_knowledge_index_id = index_id
    # Quotes fit the evidence-byte cap but expand when JSON escaped in the prompt.
    source = chunk(text='"' * 2500, score=0.99)
    retriever, generator = FakeRetriever(RetrievalResult("matches", (source,), index_id)), FakeGenerator()

    with pytest.raises(RagFailure) as error:
        asyncio.run(RagOrchestrator(sessions, retriever, generator).answer(owner, ids[0], "question"))

    assert error.value.code == "generation_input_limit"
    assert generator.calls == []


def test_context_packing_fails_when_question_exceeds_byte_budget_without_provider_call(database):
    sessions, owner, _, ids = database
    index_id = uuid4()
    with sessions.begin() as session:
        session.get(Assistant, ids[0]).active_knowledge_index_id = index_id
    source = chunk()
    retriever, generator = FakeRetriever(RetrievalResult("matches", (source,), index_id)), FakeGenerator()

    with pytest.raises(RagFailure, match="generation_input_limit"):
        asyncio.run(RagOrchestrator(sessions, retriever, generator).answer(
            owner, ids[0], "ا" * 501))

    assert generator.calls == []


@pytest.mark.parametrize("state", ["no_knowledge", "no_relevant_chunks"])
def test_no_evidence_returns_exact_fallback_without_generation(database, state):
    sessions, owner, _, ids = database
    active = uuid4() if state == "no_relevant_chunks" else None
    with sessions.begin() as session:
        session.get(Assistant, ids[0]).active_knowledge_index_id = active
    retriever = FakeRetriever(RetrievalResult(state, (), active))
    generator = FakeGenerator()

    answer = asyncio.run(RagOrchestrator(sessions, retriever, generator).answer(
        owner, ids[0], "Is there a lifetime warranty?"))

    expected = sessions().get(Assistant, ids[0]).fallback_message
    assert answer == Answer(expected, "fallback")
    assert generator.calls == []


def test_preparation_needed_is_not_misreported_as_unknown(database):
    sessions, owner, _, ids = database
    retriever = FakeRetriever(RetrievalResult("needs_preparation"))
    generator = FakeGenerator()
    with pytest.raises(RagFailure) as error:
        asyncio.run(RagOrchestrator(sessions, retriever, generator).answer(owner, ids[0], "question"))
    assert error.value.code == "knowledge_not_ready"
    assert error.value.fallback_message == sessions().get(Assistant, ids[0]).fallback_message
    assert generator.calls == []


def test_retriever_provider_failure_remains_failure_not_fallback(database):
    sessions, owner, _, ids = database
    generator = FakeGenerator()
    retriever = FakeRetriever(failure=RetrievalFailure("embedding_unavailable"))
    with pytest.raises(RagFailure) as error:
        asyncio.run(RagOrchestrator(sessions, retriever, generator).answer(owner, ids[0], "question"))
    assert error.value.code == "embedding_unavailable"
    assert generator.calls == []


def test_generation_provider_failure_is_safe_and_does_not_claim_unknown(database):
    sessions, owner, _, ids = database
    index_id, source = uuid4(), chunk()
    with sessions.begin() as session:
        session.get(Assistant, ids[0]).active_knowledge_index_id = index_id
    retriever = FakeRetriever(RetrievalResult("matches", (source,), index_id))
    generator = FakeGenerator(failure=GenerationFailure("generation_rate_limited"))
    with pytest.raises(RagFailure) as error:
        asyncio.run(RagOrchestrator(sessions, retriever, generator).answer(owner, ids[0], "question"))
    assert error.value.code == "generation_rate_limited"
    assert error.value.fallback_message == sessions().get(Assistant, ids[0]).fallback_message


def test_generation_citation_must_match_retrieved_file_chunk_and_excerpt(database):
    sessions, owner, _, ids = database
    index_id, source = uuid4(), chunk()
    with sessions.begin() as session:
        session.get(Assistant, ids[0]).active_knowledge_index_id = index_id
    retriever = FakeRetriever(RetrievalResult("matches", (source,), index_id))

    def forged(evidence):
        item = evidence[0]
        return Answer("Unsupported", "grounded", (Citation(
            uuid4(), item.chunk_id, item.filename, "invented excerpt"),))

    with pytest.raises(RagFailure, match="generation_invalid_output"):
        asyncio.run(RagOrchestrator(sessions, retriever, FakeGenerator(answer_factory=forged)).answer(
            owner, ids[0], "question"))


def test_configuration_change_during_generation_discards_answer(database):
    sessions, owner, _, ids = database
    index_id, source = uuid4(), chunk()
    with sessions.begin() as session:
        session.get(Assistant, ids[0]).active_knowledge_index_id = index_id
    retriever = FakeRetriever(RetrievalResult("matches", (source,), index_id))

    def change_draft():
        with sessions.begin() as session:
            session.get(Assistant, ids[0]).tone = "changed while generating"

    with pytest.raises(RagFailure, match="draft_changed"):
        asyncio.run(RagOrchestrator(sessions, retriever,
            FakeGenerator(during_call=change_draft)).answer(owner, ids[0], "question"))


def test_wrong_owner_does_not_call_retriever_or_generator(database):
    sessions, _, other, ids = database
    retriever, generator = FakeRetriever(RetrievalResult("no_knowledge")), FakeGenerator()
    with pytest.raises(RagFailure, match="assistant_not_found"):
        asyncio.run(RagOrchestrator(sessions, retriever, generator).answer(other, ids[0], "question"))
    assert retriever.calls == [] and generator.calls == []


def test_invalid_question_is_rejected_before_any_calls(database):
    sessions, owner, _, ids = database
    retriever, generator = FakeRetriever(), FakeGenerator()
    with pytest.raises(RagFailure, match="rag_invalid_request"):
        asyncio.run(RagOrchestrator(sessions, retriever, generator).answer(owner, ids[0], "  "))
    assert retriever.calls == [] and generator.calls == []
