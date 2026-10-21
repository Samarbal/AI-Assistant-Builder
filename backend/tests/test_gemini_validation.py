"""Task 3A: controlled HTTP only; never loads .env or contacts providers."""
import asyncio
import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_gemini as validation


def response_for(request):
    payload = json.loads(request.content)
    if request.url.path.endswith(":embedContent"):
        assert payload["embedContentConfig"]["outputDimensionality"] == 768
        assert len(payload["content"]["parts"]) == 1
        assert request.headers["x-goog-api-key"] == "test-secret"
        return httpx.Response(200, json={"embedding": {"values": [0.125] * 768},
                                        "usageMetadata": {"totalTokenCount": 25}})
    if request.url.path.endswith(":countTokens"):
        return httpx.Response(200, json={"totalTokens": 25})
    assert request.url.path.endswith("/openai/chat/completions")
    assert request.headers["Authorization"] == "Bearer test-secret"
    assert payload["model"] == "gemini-3.5-flash-lite"
    assert payload["max_tokens"] == 512
    question = payload["messages"][1]["content"]
    answer = (validation.FALLBACK if "No relevant evidence" in question else
              json.dumps({"english": "Returns are accepted within 14 days.",
                          "arabic": "يمكن الإرجاع خلال 14 يوماً."}))
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                                                   "message": {"content": answer}}],
                                    "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                              "total_tokens": 120, "secret": "test-secret"}})


def run(handler=response_for, **kwargs):
    return asyncio.run(validation.validate("test-secret", live=True, free_tier_confirmed=True,
                                           transport=httpx.MockTransport(handler), **kwargs))


def test_complete_probe_eight_requests_synthetic_only(capsys):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "generativelanguage.googleapis.com"
        assert not request.url.query
        return response_for(request)

    report = run(handler)
    assert report["status"] == "smoke_passed"
    assert report["requests_attempted"] == len(requests) == 8
    assert len(report["observations"]) == 5
    for observed in report["observations"][:3]:
        assert observed["dimension"] == 768
        assert observed["vector_count"] == 1
        assert observed["provider_count_tokens"] == 25
        assert observed["token_count_delta"] == 25 - observed["local_cl100k_tokens"]
    assert "test-secret" not in json.dumps(report)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("key,live,confirmed", [(None, True, True), ("", True, True),
                                                ("key", False, True), ("key", True, False)])
def test_missing_prerequisites_never_call_network(key, live, confirmed):
    def forbidden(request):
        pytest.fail("Network must not be called")

    report = asyncio.run(validation.validate(key, live=live, free_tier_confirmed=confirmed,
                                            transport=httpx.MockTransport(forbidden)))
    assert report["status"] == "blocked"
    assert report["requests_attempted"] == 0


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
def test_http_failure_stops_without_retries_or_sensitive_body(status):
    report = run(lambda request: httpx.Response(status, text="test-secret",
                                               headers={"Location": "https://other.example"}))
    assert report["status"] == "failed"
    assert report["requests_attempted"] == 1
    assert report["reason"] == f"provider_http_{status}"
    assert "test-secret" not in json.dumps(report)


@pytest.mark.parametrize("vector", [[], [1] * 767, [1] * 769, [0] * 768,
                                    [True] * 768, ["1"] * 768,
                                    [float("nan")] * 768, [float("inf")] * 768])
def test_reject_invalid_vectors(vector):
    with pytest.raises(validation.ValidationFailure):
        validation.validate_vector({"embedding": {"values": vector}})


def test_total_deadline_stops_and_counts_attempt(monkeypatch):
    monkeypatch.setattr(validation, "DEADLINE", 0.01)

    async def slow(request):
        await asyncio.sleep(0.1)
        return response_for(request)

    report = run(slow)
    assert report["reason"] == "provider_deadline_exceeded"
    assert report["requests_attempted"] == 1


def test_hard_request_budget():
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response_for)) as client:
            probe = validation.Probe(client, "test-secret")
            probe.attempts = 8
            with pytest.raises(validation.ValidationFailure, match="request_budget_exhausted"):
                await probe.post("unused", {})
    asyncio.run(check())


@pytest.mark.parametrize("failure", ["wrong_fact", "missing_arabic", "truncated", "fallback"])
def test_generation_checks_fail_closed(failure):
    def handler(request):
        response = response_for(request)
        if request.url.path.endswith("/chat/completions"):
            data = response.json()
            choice = data["choices"][0]
            if failure == "truncated":
                choice["finish_reason"] = "length"
            elif failure == "fallback":
                if "No relevant evidence" in request.content.decode():
                    choice["message"]["content"] = validation.FALLBACK + " Extra."
            else:
                choice["message"]["content"] = json.dumps({
                    "english": "45 days" if failure == "wrong_fact" else "14 days",
                    "arabic": "14 days"})
            return httpx.Response(200, json=data)
        return response

    assert run(handler)["status"] == "failed"


def test_absent_usage_not_invented():
    assert validation.numeric_usage(None) == {}
    assert validation.numeric_usage({"total_tokens": True, "prompt_tokens": -1}) == {}


def test_invalid_json_sanitized():
    report = run(lambda request: httpx.Response(200, text="test-secret"))
    assert report["reason"] == "invalid_provider_json"
    assert report["requests_attempted"] == 1
