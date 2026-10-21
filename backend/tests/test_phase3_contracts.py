"""Offline contract examples only: no API, provider, embedding or database calls.

These checks establish test-oracle integrity, not implemented RAG acceptance.
Short fixture IDs stand for server UUIDs; production API UUID parsing is deferred.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[2]
     / "docs/ai-sdlc/contracts/phase-3-fixtures.json").read_text(encoding="utf-8")
)
DOCUMENTS = {row["id"]: row for row in FIXTURES["documents"]}
DRAFTS = {row["id"]: row for row in FIXTURES["drafts"]}


def check_request(value):
    """Executable specification for the proposed independent-turn request."""
    assert set(value) == {"message"}
    assert isinstance(value["message"], str)
    assert value["message"].strip()
    assert len(value["message"]) <= 4000
    # Model token count cannot be checked until the tokenizer is selected.


def check_response(value, *, owner, assistant, fallback, allowed_files):
    """Validate synthetic response examples against their supplied evidence."""
    assert set(value) == {"answer", "outcome", "citations"}
    assert isinstance(value["answer"], str) and value["answer"].strip()
    assert value["outcome"] in {"grounded", "fallback"}
    citations = value["citations"]
    assert isinstance(citations, list) and len(citations) <= 5
    if value["outcome"] == "fallback":
        assert value["answer"] == fallback
        assert citations == []
        return
    assert citations
    assert len({c["chunk_id"] for c in citations}) == len(citations)
    for citation in citations:
        assert set(citation) == {"file_id", "chunk_id", "filename", "excerpt"}
        assert citation["file_id"] in allowed_files
        source = DOCUMENTS[citation["file_id"]]
        assert (source["owner"], source["assistant"]) == (owner, assistant)
        assert source["attached"]
        assert 0 < len(citation["excerpt"]) <= 600
        assert citation["excerpt"] in source["text"]


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=lambda row: row["id"])
def test_synthetic_case_integrity(case):
    check_request(case["request"])
    assert case["criteria"]
    for source_id in case["sources"]:
        source = DOCUMENTS[source_id]
        assert source["owner"] == case["owner"]
        assert source["assistant"] == case["assistant"]
        assert source["attached"]
    evidence = "\n".join(DOCUMENTS[key]["text"] for key in case["sources"])
    for fact in case.get("expected_facts", []):
        assert fact in evidence
    assert not set(case.get("excluded_sources", [])) & set(case["sources"])
    if case["kind"] == "unknown":
        assert case["expected_fallback"] == DRAFTS[case["draft"]]["fallback"]
        assert case["generation_calls"] == 0 and not case["sources"]
    if case["kind"] == "denied":
        assert case["http_status"] == 404 and case["generation_calls"] == 0


def test_bilingual_coverage_and_acceptance_mapping():
    cases = FIXTURES["cases"]
    for kind in ("known", "unknown", "injection", "denied"):
        assert {c["language"] for c in cases if c["kind"] == kind} == {"ar", "en"}
    assert {"AC-008", "AC-009", "AC-017", "AC-018"} <= {
        ac for case in cases for ac in case["criteria"]
    }
    assert DRAFTS["initial"]["fallback"] != DRAFTS["updated"]["fallback"]
    assert DRAFTS["initial"]["tone"] != DRAFTS["updated"]["tone"]


@pytest.mark.parametrize("field", ["owner_id", "model", "history", "prompt", "index_id"])
def test_request_examples_reject_client_authority_and_provider_controls(field):
    with pytest.raises(AssertionError):
        check_request({"message": "Hello", field: "not allowed"})


@pytest.mark.parametrize("value", ["", "   ", None, "x" * 4001])
def test_message_contract_rejects_invalid_inputs(value):
    with pytest.raises(AssertionError):
        check_request({"message": value})


def validate(value, **overrides):
    options = dict(owner="owner-a", assistant="support-a",
                   fallback=DRAFTS["initial"]["fallback"], allowed_files={"a-en"})
    options.update(overrides)
    check_response(value, **options)


@pytest.mark.parametrize("kind", ["grounded", "fallback"])
def test_response_examples(kind):
    validate(FIXTURES["responses"][kind])


@pytest.mark.parametrize("corruption", [
    "foreign_owner", "other_assistant", "removed", "fabricated_excerpt",
    "page_number", "fallback_suffix", "fallback_citation", "unknown_source",
])
def test_response_oracle_rejects_security_and_grounding_counterexamples(corruption):
    value = deepcopy(FIXTURES["responses"]["grounded"])
    allowed = {"a-en"}
    if corruption in {"foreign_owner", "other_assistant", "removed"}:
        key = {"foreign_owner": "b-en", "other_assistant": "a-other",
               "removed": "a-removed"}[corruption]
        value["citations"][0].update(file_id=key, excerpt=DOCUMENTS[key]["text"])
        allowed.add(key)  # Ensure ownership/removal checks, not just membership, reject it.
    elif corruption == "fabricated_excerpt":
        value["citations"][0]["excerpt"] = "Refunds last 999 days."
    elif corruption == "page_number":
        value["citations"][0]["page"] = 9
    elif corruption == "unknown_source":
        value["citations"][0]["file_id"] = "invented"
    else:
        citations = value["citations"]
        value = deepcopy(FIXTURES["responses"]["fallback"])
        if corruption == "fallback_suffix":
            value["answer"] += " But we probably offer a warranty."
        else:
            value["citations"] = citations
    with pytest.raises(AssertionError):
        validate(value, allowed_files=allowed)


def test_fallback_example_must_change_after_draft_change():
    value = deepcopy(FIXTURES["responses"]["fallback"])
    with pytest.raises(AssertionError):
        validate(value, fallback=DRAFTS["updated"]["fallback"])
    value["answer"] = DRAFTS["updated"]["fallback"]
    validate(value, fallback=DRAFTS["updated"]["fallback"])
