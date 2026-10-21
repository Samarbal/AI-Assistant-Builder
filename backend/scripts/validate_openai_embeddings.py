"""Synthetic embedding smoke test; independent of Groq configuration.

Four requests maximum (three single inputs and one batch), no retries. Requires
operator confirmation of available credit and approval of the $0.001 ceiling.
"""
import argparse
import asyncio
import json
import logging
import math
import os
from pathlib import Path
import time

import httpx
from dotenv import dotenv_values

from assistant_builder.chunking import TiktokenTokenizer
from validate_gemini import synthetic_texts, ValidationFailure

MODEL = "text-embedding-3-small"
DIMENSION = 768
URL = "https://api.openai.com/v1/embeddings"
DEADLINE = 12.0
PRICE_PER_TOKEN = 0.02 / 1_000_000


def compare_vectors(individual, batch):
    """Report coordinate diagnostics and a bounded cosine-error acceptance gate.

Rows are batch inputs, columns individual inputs, both in returned-index order.
1e-12 handles floating-point tie noise only; it is not a similarity threshold.
"""
    if len(individual) != len(batch) or not individual:
        raise ValidationFailure("comparison_count_mismatch")
    for vector in individual + batch:
        if (len(vector) != DIMENSION or any(type(v) not in (int, float)
                or not math.isfinite(v) for v in vector) or not 0 < math.hypot(*vector) < math.inf):
            raise ValidationFailure("invalid_comparison_vector")
    normalized_individual = [[x / math.hypot(*v) for x in v] for v in individual]
    normalized_batch = [[x / math.hypot(*v) for x in v] for v in batch]
    matrix = [[math.fsum(x * y for x, y in zip(b, a))
               for a in normalized_individual] for b in normalized_batch]
    differences = []
    for a, b in zip(individual, batch):
        errors = [abs(x - y) for x, y in zip(a, b)]
        differences.append({"max_absolute_difference": max(errors),
                            "mean_absolute_difference": math.fsum(errors) / DIMENSION,
                            "l2_difference": math.hypot(*errors),
                            "individual_norm": math.hypot(*a), "batch_norm": math.hypot(*b)})
    nearest = [max(range(len(row)), key=row.__getitem__) for row in matrix]
    margins = [row[i] - max((v for j, v in enumerate(row) if j != i), default=-1)
               for i, row in enumerate(matrix)]
    # Unit-vector L2 <= 0.002 implies cosine >= 1 - 0.002**2/2.
    # Thus cosine scores against any fixed unit query differ by at most 0.002.
    # Require a mapping margin > twice that bound, plus <=0.1% norm change.
    numerical_matches = [matrix[i][i] >= 0.999998 and
                         abs(d["individual_norm"] - d["batch_norm"]) <= 0.001
                         for i, d in enumerate(differences)]
    return {"cosine_matrix_batch_rows_individual_columns": matrix,
            "coordinate_differences": differences, "nearest_individual_indices": nearest,
            "diagonal_margins": margins,
            "numerical_matches": numerical_matches,
            "mapping_margin_sufficient": all(m > 0.004 for m in margins),
            "unique_diagonal_mapping": all(i == j and margin > 1e-12
                                           for i, (j, margin) in enumerate(zip(nearest, margins)))}


def vectors_and_usage(body, count):
    if body.get("model") != MODEL:
        raise ValidationFailure("unexpected_model")
    data = body.get("data")
    if not isinstance(data, list) or len(data) != count:
        raise ValidationFailure("vector_count_mismatch")
    vectors = {}
    for item in data:
        index = item.get("index")
        if type(index) is not int or not 0 <= index < count or index in vectors:
            raise ValidationFailure("invalid_vector_indices")
        vector = item.get("embedding")
        if not isinstance(vector, list) or len(vector) != DIMENSION:
            raise ValidationFailure("dimension_mismatch")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
            raise ValidationFailure("non_finite_vector")
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm == 0:
            raise ValidationFailure("invalid_vector_norm")
        vectors[index] = vector
    usage = body.get("usage", {})
    prompt, total = usage.get("prompt_tokens"), usage.get("total_tokens")
    if type(prompt) is not int or prompt <= 0 or type(total) is not int or total != prompt:
        raise ValidationFailure("invalid_usage")
    return [vectors[i] for i in range(count)], {"prompt_tokens": prompt, "total_tokens": total}


async def validate(key, *, approved=False, transport=None):
    report = {"status": "blocked", "requests_attempted": 0, "model": MODEL,
              "requested_dimensions": DIMENSION, "observations": []}
    if not key or not key.strip() or not approved:
        return dict(report, reason="key_and_credit_budget_approval_required")
    texts = list(synthetic_texts().values())
    tokenizer = TiktokenTokenizer()
    counts = [len(tokenizer.encode(t)) for t in texts]
    # Every text is sent once alone and once in the batch. No arbitrary input.
    total_expected = 2 * sum(counts)
    if total_expected > 1000:
        return dict(report, reason="synthetic_token_budget_exceeded")
    report["estimated_cost_usd"] = total_expected * PRICE_PER_TOKEN
    report["local_tokens_per_input"] = counts
    single_vectors = []
    async with httpx.AsyncClient(transport=transport or httpx.AsyncHTTPTransport(retries=0),
                                 follow_redirects=False, trust_env=False,
                                 timeout=httpx.Timeout(12, connect=3)) as client:
        try:
            for index, inputs in enumerate([[t] for t in texts] + [texts]):
                if report["requests_attempted"] >= 4:
                    raise ValidationFailure("request_budget_exhausted")
                report["requests_attempted"] += 1
                start = time.monotonic()
                async with asyncio.timeout(DEADLINE):
                    async with client.stream("POST", URL,
                        headers={"Authorization": "Bearer " + key},
                        json={"model": MODEL, "input": inputs, "dimensions": DIMENSION,
                              "encoding_format": "float"}) as response:
                        if response.status_code != 200:
                            raise ValidationFailure(f"provider_http_{response.status_code}")
                        raw = bytearray()
                        async for part in response.aiter_bytes(chunk_size=8192):
                            raw.extend(part)
                            if len(raw) > 262144:
                                raise ValidationFailure("response_size_exceeded")
                latency = round(time.monotonic() - start, 3)
                vectors, usage = vectors_and_usage(json.loads(raw), len(inputs))
                expected = counts[index] if index < 3 else sum(counts)
                observed = {"case": ["english", "arabic", "mixed", "batch"][index],
                            "vector_count": len(vectors), "dimensions": [len(v) for v in vectors],
                            "latency_seconds": latency, "usage": usage,
                            "local_cl100k_tokens": expected,
                            "token_usage_matches": usage["prompt_tokens"] == expected}
                report["observations"].append(observed)
                if usage["prompt_tokens"] != expected:
                    raise ValidationFailure("tokenizer_usage_mismatch")
                if index < 3:
                    single_vectors.append(vectors[0])
                else:
                    observed["diagnostics"] = compare_vectors(single_vectors, vectors)
                    matches = [all(math.isclose(a, b, rel_tol=1e-4, abs_tol=1e-6)
                                   for a, b in zip(one, batch))
                               for one, batch in zip(single_vectors, vectors)]
                    observed["batch_matches_single_inputs"] = matches
                    diagnostics = observed["diagnostics"]
                    if not (all(diagnostics["numerical_matches"])
                            and diagnostics["unique_diagonal_mapping"]
                            and diagnostics["mapping_margin_sufficient"]):
                        raise ValidationFailure("batch_order_or_consistency_mismatch")
            report["status"] = "smoke_passed"
        except ValidationFailure as exc:
            report.update(status="failed", reason=str(exc))
        except (TimeoutError, httpx.TimeoutException):
            report.update(status="failed", reason="provider_timeout")
        except httpx.HTTPError:
            report.update(status="failed", reason="provider_transport_failure")
        except Exception:
            report.update(status="failed", reason="malformed_response_or_local_failure")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-credit-budget", action="store_true")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    config = {**dotenv_values(Path(__file__).resolve().parents[1] / ".env"), **os.environ}
    report = asyncio.run(validate(config.get("OPENAI_API_KEY"), approved=args.confirm_credit_budget))
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "smoke_passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
