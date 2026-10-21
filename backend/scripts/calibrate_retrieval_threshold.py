"""One-request, synthetic-only cosine threshold calibration diagnostic.

Requires explicit --live. Sends exactly one batch (3 synthetic passages and 5
synthetic questions) to the configured embedding adapter. Prints scores only.
This is an initial fixture calibration, not a universal relevance guarantee.
"""
import argparse
import asyncio
import math
import time

from assistant_builder.config import get_settings
from assistant_builder.embeddings import EmbeddingFailure, OpenAIEmbeddingProvider


PASSAGES = (
    "Returns: Unused items may be returned within fourteen days of delivery. Contact support with your order number.",
    "مدة التوصيل المعتادة إلى المدن الرئيسية ثلاثة أيام عمل. يمكن تتبع الطلب من صفحة الطلبات.",
    "Support hours: Monday to Friday, 09:00–17:00. ساعات الدعم من الاثنين إلى الجمعة، من التاسعة حتى الخامسة.",
)
QUESTIONS = (
    ("known_en", "How many days after delivery can I return an unused item?", 0),
    ("known_ar", "كم يوم عمل يستغرق التوصيل إلى المدن الرئيسية؟", 1),
    ("known_mixed", "What are your support hours? ما ساعات الدعم؟", 2),
    ("unknown_en", "Do you provide a lifetime warranty for electronics?", None),
    ("unknown_ar", "هل المتجر مفتوح في أيام العطل الرسمية؟", None),
)


def cosine(left, right):
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.hypot(*left)
    right_norm = math.hypot(*right)
    if not left_norm or not right_norm:
        raise ValueError("zero vector")
    return dot / (left_norm * right_norm)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="authorize the single synthetic request")
    args = parser.parse_args()
    if not args.live:
        parser.error("pass --live to send the one fixed synthetic batch")
    settings = get_settings()
    provider = OpenAIEmbeddingProvider(settings)
    texts = PASSAGES + tuple(row[1] for row in QUESTIONS)
    started = time.perf_counter()
    result = await provider.embed(texts)
    latency = time.perf_counter() - started
    if len(result.vectors) != len(texts) or result.dimensions != 768:
        raise EmbeddingFailure("embedding_invalid_output")
    vectors = result.vectors
    scores = [[cosine(vectors[3 + question_index], vectors[passage_index])
               for passage_index in range(len(PASSAGES))]
              for question_index in range(len(QUESTIONS))]
    relevant = [scores[q][expected] for q, (_, _, expected) in enumerate(QUESTIONS)
                if expected is not None]
    irrelevant = [scores[q][p] for q, (_, _, expected) in enumerate(QUESTIONS)
                  for p in range(len(PASSAGES)) if expected is None or p != expected]
    print(f"requests=1 inputs={len(texts)} dimensions={result.dimensions} "
          f"tokens={result.total_tokens} latency_seconds={latency:.3f}")
    print("cosine_matrix (rows=question ids, columns=passage-0/1/2):")
    for (name, _, _), row in zip(QUESTIONS, scores):
        print(name + ": " + ", ".join(f"{value:.6f}" for value in row))
    lower, upper = max(irrelevant), min(relevant)
    print(f"max_irrelevant={lower:.6f} min_relevant={upper:.6f}")
    if lower < upper:
        print(f"separating_initial_threshold={(lower + upper) / 2:.6f}")
    else:
        print("separating_initial_threshold=NONE; fixtures do not support a safe boundary")


if __name__ == "__main__":
    asyncio.run(main())
