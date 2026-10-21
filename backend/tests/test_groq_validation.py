"""Offline HTTP fixtures; no credentials or provider access."""
import asyncio
import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_groq as probe


def handler(request):
    assert request.url.host == "api.groq.com"
    assert request.headers["Authorization"] == "Bearer test-key"
    if request.method == "GET":
        return httpx.Response(200, json={"id": probe.MODEL})
    data = json.loads(request.content)
    assert data["max_completion_tokens"] == 512
    assert data["reasoning_format"] == "hidden"
    answer = (probe.FALLBACK if "No relevant evidence" in data["messages"][1]["content"]
              else "Returns within 14 days. الإرجاع خلال 14 يوماً.")
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": answer}}],
                                    "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130}})


def run(callback=handler, **kwargs):
    return asyncio.run(probe.validate("test-key", transport=httpx.MockTransport(callback), **kwargs))


def test_success_five_requests():
    report = run(confirmed=True)
    assert report["status"] == "smoke_passed"
    assert report["requests_attempted"] == 5
    assert len(report["observations"]) == 4
    assert "test-key" not in json.dumps(report)


def test_gate_no_requests():
    assert run()["requests_attempted"] == 0


def test_remaining_fallback_budget_one_request():
    report = run(confirmed=True, fallback_only=True)
    assert report["requests_attempted"] == 1
    assert report["status"] == "smoke_passed"


def test_written_numbers_are_valid_facts():
    def words(req):
        response = handler(req)
        if req.method == "POST" and "No relevant evidence" not in req.content.decode():
            data = response.json()
            data["choices"][0]["message"]["content"] = "أربع عشرة يومًا. Fourteen days."
            return httpx.Response(200, json=data)
        return response
    assert run(words, confirmed=True)["status"] == "smoke_passed"


@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
def test_errors_no_retry_or_raw_error(status):
    report = run(lambda req: httpx.Response(status, text="test-key"), confirmed=True)
    assert report["requests_attempted"] == 1
    assert report["reason"] == f"provider_http_{status}"
    assert "test-key" not in json.dumps(report)


def test_total_timeout(monkeypatch):
    monkeypatch.setattr(probe, "DEADLINE", 0.01)
    async def slow(req):
        await asyncio.sleep(0.1)
        return handler(req)
    report = run(slow, confirmed=True)
    assert report["requests_attempted"] == 1
    assert report["reason"] == "provider_deadline_exceeded"


def test_bad_answer_stops():
    def bad(req):
        response = handler(req)
        if req.method == "POST":
            data = response.json()
            data["choices"][0]["message"]["content"] = "45 days"
            return httpx.Response(200, json=data)
        return response
    report = run(bad, confirmed=True)
    assert report["reason"] == "answer_check_failed"
    assert report["requests_attempted"] == 2
