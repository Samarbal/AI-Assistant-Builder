"""Offline OpenAI response validation; no .env reads or live requests."""
import asyncio
import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_openai_embeddings as probe


def handler(req):
    assert str(req.url) == probe.URL
    assert req.headers["Authorization"] == "Bearer test-secret"
    payload = json.loads(req.content)
    assert payload["dimensions"] == 768
    tokens = sum(len(probe.TiktokenTokenizer().encode(t)) for t in payload["input"])
    return httpx.Response(200, json={"model": probe.MODEL,
        "data": [{"index": i, "embedding": [1.0 if j == len(t) % 768 else 0.0 for j in range(768)]}
                 for i, t in reversed(list(enumerate(payload["input"])))],
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens}})


def run(callback=handler, approved=True):
    return asyncio.run(probe.validate("test-secret", approved=approved,
                                      transport=httpx.MockTransport(callback)))


def test_success_reorders_indices_and_compares_batch():
    report = run()
    assert report["status"] == "smoke_passed"
    assert report["requests_attempted"] == 4
    assert report["observations"][-1]["batch_matches_single_inputs"] == [True] * 3
    assert "test-secret" not in json.dumps(report)


def test_missing_approval_no_calls():
    assert run(approved=False)["requests_attempted"] == 0


@pytest.mark.parametrize("status", [401, 403, 429, 404, 500, 302])
def test_auth_quota_errors_no_retry(status):
    report = run(lambda req: httpx.Response(status, text="test-secret"))
    assert report["requests_attempted"] == 1
    assert report["reason"] == f"provider_http_{status}"
    assert "test-secret" not in json.dumps(report)


@pytest.mark.parametrize("change", ["dimension", "nan", "count", "index", "usage", "model", "zero"])
def test_malformed_vectors(change):
    body = {"model": probe.MODEL, "data": [{"index": 0, "embedding": [1.0] * 768}],
            "usage": {"prompt_tokens": 5, "total_tokens": 5}}
    if change == "dimension": body["data"][0]["embedding"].pop()
    if change == "nan": body["data"][0]["embedding"][0] = float("nan")
    if change == "count": body["data"] = []
    if change == "index": body["data"][0]["index"] = True
    if change == "usage": body["usage"]["total_tokens"] = 6
    if change == "model": body["model"] = "other"
    if change == "zero": body["data"][0]["embedding"] = [0] * 768
    with pytest.raises(probe.ValidationFailure):
        probe.vectors_and_usage(body, 1)


def test_total_timeout(monkeypatch):
    monkeypatch.setattr(probe, "DEADLINE", 0.01)
    async def slow(req):
        await asyncio.sleep(0.1)
        return handler(req)
    report = run(slow)
    assert report["reason"] == "provider_timeout"
    assert report["requests_attempted"] == 1


def test_invalid_json():
    report = run(lambda req: httpx.Response(200, text="test-secret"))
    assert report["status"] == "failed"
    assert "test-secret" not in json.dumps(report)


def test_duplicate_batch_indices_rejected():
    body = {"model": probe.MODEL, "data": [{"index": 0, "embedding": [1.0] * 768}] * 2,
            "usage": {"prompt_tokens": 5, "total_tokens": 5}}
    with pytest.raises(probe.ValidationFailure, match="invalid_vector_indices"):
        probe.vectors_and_usage(body, 2)


def test_batch_consistency_failure_is_not_success():
    def changed(req):
        response = handler(req)
        body = response.json()
        if len(body["data"]) == 3:
            body["data"][0]["embedding"][0] += 0.1
        return httpx.Response(200, json=body)
    report = run(changed)
    assert report["status"] == "failed"
    assert report["reason"] == "batch_order_or_consistency_mismatch"


def test_diagnostics_distinguish_small_noise_from_swaps():
    first = [1.0] + [0.0] * 767
    second = [0.0, 1.0] + [0.0] * 766
    noisy = [1.0, 0.00001] + [0.0] * 766
    metrics = probe.compare_vectors([first, second], [noisy, second])
    assert metrics["unique_diagonal_mapping"]
    assert metrics["coordinate_differences"][0]["max_absolute_difference"] == 0.00001
    assert metrics["coordinate_differences"][0]["mean_absolute_difference"] == pytest.approx(0.00001 / 768)
    assert metrics["cosine_matrix_batch_rows_individual_columns"][0][0] > 0.999999
    swapped = probe.compare_vectors([first, second], [second, first])
    assert not swapped["unique_diagonal_mapping"]
    assert swapped["nearest_individual_indices"] == [1, 0]


def test_diagnostics_identical_inputs_are_ambiguous():
    vector = [1.0] * 768
    assert not probe.compare_vectors([vector, vector], [vector, vector])["unique_diagonal_mapping"]


def test_numeric_tolerance_bounds_direction_and_norm():
    first = [1.0] + [0.0] * 767
    second = [0.0, 1.0] + [0.0] * 766
    small = [1.0, 0.0009] + [0.0] * 766
    accepted = probe.compare_vectors([first, second], [small, second])
    assert all(accepted["numerical_matches"])
    assert accepted["mapping_margin_sufficient"]
    drift = [1.0, 0.01] + [0.0] * 766
    assert not probe.compare_vectors([first], [drift])["numerical_matches"][0]
    scaled = [1.01] + [0.0] * 767
    assert not probe.compare_vectors([first], [scaled])["numerical_matches"][0]
