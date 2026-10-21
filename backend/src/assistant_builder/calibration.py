"""Safe, bounded retrieval calibration over a fixed set of question fixtures.

Question text and retrieved document contents are never included in reports.
"""
from dataclasses import dataclass
import math
import time
from typing import Callable, Sequence

from .embeddings import EmbeddingFailure, EmbeddingProvider


@dataclass(frozen=True)
class CalibrationQuestion:
    question_id: str
    text: str
    relevant_chunk_ids: frozenset[str]


async def calibrate_questions(
    questions: Sequence[CalibrationQuestion],
    provider: EmbeddingProvider,
    fetch_top5: Callable[[tuple[float, ...]], Sequence[tuple[str, float]]],
    *,
    current_threshold: float,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Embed seven questions in one batch, then score current indexed chunks.

    ``fetch_top5`` must be a read-only, owner-scoped query and return only chunk
    identifiers and cosine scores. Reports contain ranks/scores/relevance only.
    """
    if (len(questions) != 7 or len({q.question_id for q in questions}) != 7
            or sum(bool(q.relevant_chunk_ids) for q in questions) != 4
            or any(not isinstance(q.question_id, str) or not q.question_id
                   or not isinstance(q.text, str) or not q.text.strip() for q in questions)
            or isinstance(current_threshold, bool)
            or not math.isfinite(current_threshold) or not 0 <= current_threshold <= 1):
        raise ValueError("calibration_fixture_invalid")

    started = time.perf_counter()
    if progress:
        progress("embedding_started batch=7")
    try:
        embedded = await provider.embed(tuple(q.text for q in questions))
    except EmbeddingFailure:
        raise RuntimeError("calibration_provider_failure") from None
    except Exception:
        raise RuntimeError("calibration_provider_failure") from None
    latency = time.perf_counter() - started
    if progress:
        progress("embedding_completed")
    if (embedded.dimensions != 768 or len(embedded.vectors) != 7
            or not embedded.model or embedded.prompt_tokens < 0
            or embedded.total_tokens != embedded.prompt_tokens):
        raise RuntimeError("calibration_embedding_invalid")

    results = []
    known_best = []
    unknown_max = []
    known_hits = 0
    unknown_false_positives = 0
    for question, vector in zip(questions, embedded.vectors, strict=True):
        if (len(vector) != 768 or any(not math.isfinite(v) for v in vector)
                or math.hypot(*vector) == 0):
            raise RuntimeError("calibration_embedding_invalid")
        try:
            rows = tuple(fetch_top5(vector))
        except Exception:
            raise RuntimeError("calibration_database_failure") from None
        if (len(rows) > 5
                or any(not isinstance(chunk_id, str) or not chunk_id for chunk_id, _ in rows)
                or len({chunk_id for chunk_id, _ in rows}) != len(rows)):
            raise RuntimeError("calibration_query_invalid")
        scored = []
        raw_scores = []
        for rank, (chunk_id, score) in enumerate(rows, 1):
            if (not isinstance(chunk_id, str) or not chunk_id
                    or isinstance(score, bool) or not isinstance(score, (int, float))
                    or not math.isfinite(score) or not -1 <= score <= 1):
                raise RuntimeError("calibration_query_invalid")
            raw_scores.append(float(score))
            relevant = chunk_id in question.relevant_chunk_ids
            scored.append({"rank": rank, "similarity": round(float(score), 6),
                           "relevant": relevant})
        if question.relevant_chunk_ids:
            relevant_scores = [score for (chunk_id, _), score in zip(rows, raw_scores, strict=True)
                               if chunk_id in question.relevant_chunk_ids]
            if relevant_scores:
                best = max(relevant_scores)
                known_best.append(best)
                if best >= current_threshold:
                    known_hits += 1
        else:
            maximum = max(raw_scores, default=-1.0)
            unknown_max.append(maximum)
            if maximum >= current_threshold:
                unknown_false_positives += 1
        results.append({"id": question.question_id, "top5": scored})
        if progress:
            progress(f"scores_completed={len(results)}/7")

    max_unknown = max(unknown_max) if unknown_max else None
    min_known = min(known_best) if len(known_best) == 4 else None
    if max_unknown is not None and min_known is not None and max_unknown < min_known:
        recommended = round((max_unknown + min_known) / 2, 6)
        separation = "separable_on_fixtures"
    else:
        recommended = None
        separation = "no_safe_separation"
    return {
        "request_count": 1,
        "input_count": 7,
        "dimensions": embedded.dimensions,
        "tokens": embedded.total_tokens,
        "latency_seconds": round(latency, 3),
        "current_threshold": current_threshold,
        "known_hits_at_current": known_hits,
        "known_total": 4,
        "unknown_false_positives_at_current": unknown_false_positives,
        "unknown_total": 3,
        "max_unknown_similarity": None if max_unknown is None else round(max_unknown, 6),
        "min_best_known_similarity": min_known,
        "recommended_threshold": recommended,
        "separation": separation,
        "questions": results,
    }
