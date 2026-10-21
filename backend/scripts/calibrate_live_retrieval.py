"""One-batch, read-only retrieval calibration. Requires an explicit --live flag.

Fixture JSON fields: owner_id, assistant_id, index_id, and exactly seven
questions with id, text, and relevant_chunk_ids (four known, three unknown).
Question text and document contents are never printed or logged.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from assistant_builder.calibration import CalibrationQuestion, calibrate_questions
from assistant_builder.config import get_settings
from assistant_builder.db import create_database_engine, set_owner_identity
from assistant_builder.embeddings import OpenAIEmbeddingProvider


_TOP5_SQL = text("""
SELECT c.id::text AS chunk_id,
       1 - (c.embedding <=> CAST(:query_vector AS public.vector(768))) AS similarity
  FROM public.assistants a
  JOIN public.knowledge_indexes i
    ON i.id=a.active_knowledge_index_id AND i.assistant_id=a.id AND i.owner_id=a.owner_id
  JOIN public.knowledge_chunks c
    ON c.index_id=i.id AND c.assistant_id=i.assistant_id AND c.owner_id=i.owner_id
  JOIN public.knowledge_index_sources src
    ON src.index_id=c.index_id AND src.file_id=c.file_id
   AND src.assistant_id=c.assistant_id AND src.owner_id=c.owner_id
  JOIN public.knowledge_files f
    ON f.id=c.file_id AND f.assistant_id=c.assistant_id AND f.owner_id=c.owner_id
  JOIN public.knowledge_file_text t
    ON t.file_id=f.id AND t.assistant_id=f.assistant_id AND t.owner_id=f.owner_id
 WHERE a.id=:assistant_id AND a.owner_id=:owner_id
   AND a.active_knowledge_index_id=:index_id AND i.state='ready'
   AND i.embedding_provider='openai' AND i.embedding_model=:model AND i.vector_dimension=768
   AND f.removed_at IS NULL AND f.processing_state='extracted'
   AND t.extraction_version=src.extraction_version
   AND c.extraction_version=src.extraction_version
   AND c.source_sha256=src.source_sha256
 ORDER BY c.embedding <=> CAST(:query_vector AS public.vector(768)), c.id
 LIMIT 5
""")
_SAFE_FAILURE_CODES = {
    "calibration_fixture_invalid", "calibration_threshold_unset",
    "calibration_runtime_role", "calibration_index_not_ready",
    "calibration_provider_failure", "calibration_embedding_invalid",
    "calibration_database_failure", "calibration_query_invalid",
}


def _uuid(value):
    try:
        return UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("calibration_fixture_invalid") from None


def _load_fixture(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        questions = tuple(CalibrationQuestion(
            question_id=item["id"], text=item["text"],
            relevant_chunk_ids=frozenset(item["relevant_chunk_ids"]),
        ) for item in data["questions"])
        if (len(questions) != 7 or any(not q.question_id or not q.text.strip()
                                       or any(not isinstance(cid, str) for cid in q.relevant_chunk_ids)
                                       for q in questions)
                or sum(bool(q.relevant_chunk_ids) for q in questions) != 4):
            raise ValueError()
        return (_uuid(data["owner_id"]), _uuid(data["assistant_id"]),
                _uuid(data["index_id"]), questions)
    except Exception:
        raise ValueError("calibration_fixture_invalid") from None


def _preflight(factory, owner_id, assistant_id, index_id):
    with factory.begin() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        if session.scalar(text("SELECT current_user")) != "assistant_runtime":
            raise RuntimeError("calibration_runtime_role")
        set_owner_identity(session, owner_id)
        row = session.execute(text("""
          SELECT a.active_knowledge_index_id, i.state, i.total_chunks,
                 i.completed_chunks, count(c.id)
            FROM public.assistants a
            JOIN public.knowledge_indexes i
              ON i.id=a.active_knowledge_index_id AND i.assistant_id=a.id AND i.owner_id=a.owner_id
            LEFT JOIN public.knowledge_chunks c
              ON c.index_id=i.id AND c.assistant_id=i.assistant_id AND c.owner_id=i.owner_id
           WHERE a.id=:assistant AND a.owner_id=:owner
           GROUP BY a.active_knowledge_index_id, i.state, i.total_chunks, i.completed_chunks
        """), {"assistant": assistant_id, "owner": owner_id}).one_or_none()
        if (row is None or row[0] != index_id or row[1] != "ready"
                or row[2] != row[3] or row[2] != row[4] or row[2] < 1):
            raise RuntimeError("calibration_index_not_ready")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--live", action="store_true",
                        help="explicitly authorize one configured embedding batch")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; no provider request was made")

    stage = "fixture"
    engine = None
    try:
        owner_id, assistant_id, index_id, questions = _load_fixture(args.fixture)
        stage = "configuration"
        settings = get_settings()
        if settings.retrieval_min_similarity is None:
            raise RuntimeError("calibration_threshold_unset")
        stage = "database_preflight"
        engine = create_database_engine()
        factory = sessionmaker(engine, expire_on_commit=False)
        _preflight(factory, owner_id, assistant_id, index_id)
        stage = "provider_configuration"
        provider = OpenAIEmbeddingProvider(settings)

        def fetch_top5(vector):
            nonlocal stage
            stage = "database_scoring"
            literal = "[" + ",".join(format(float(value), ".9g") for value in vector) + "]"
            with factory.begin() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                set_owner_identity(session, owner_id)
                rows = session.execute(_TOP5_SQL, {
                    "query_vector": literal, "assistant_id": assistant_id,
                    "owner_id": owner_id, "index_id": index_id,
                    "model": settings.embedding_model,
                }).all()
                return tuple((row.chunk_id, float(row.similarity)) for row in rows)

        stage = "query_embedding"
        print("CALIBRATION_STAGE preflight_passed", flush=True)
        report = asyncio.run(calibrate_questions(
            questions, provider, fetch_top5,
            current_threshold=settings.retrieval_min_similarity,
            progress=lambda message: print(f"CALIBRATION_STAGE {message}", flush=True),
        ))
        stage = "complete"
        print("CALIBRATION_REPORT " + json.dumps(report, separators=(",", ":")), flush=True)
        return 0
    except Exception as exc:
        code = str(exc) if str(exc) in _SAFE_FAILURE_CODES else "calibration_failed"
        print(f"CALIBRATION_STOP stage={stage} code={code}", flush=True)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
