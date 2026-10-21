"""Owner-scoped exact-cosine retrieval from an assistant's active index."""
from dataclasses import dataclass
import math
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .db import set_owner_identity
from .embeddings import EmbeddingFailure, EmbeddingProvider

MAX_RETRIEVAL_TOP_K = 5
VECTOR_DIMENSION = 768


class RetrievalFailure(Exception):
    """Safe retrieval failure code; never includes query, evidence, or provider details."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RetrievedChunk:
    file_id: UUID
    chunk_id: UUID
    filename: str
    text: str
    similarity: float
    start_offset: int
    end_offset: int
    extraction_version: str


@dataclass(frozen=True)
class RetrievalResult:
    state: str
    chunks: tuple[RetrievedChunk, ...] = ()
    index_id: UUID | None = None


class Retriever(Protocol):
    async def retrieve(self, owner_id: UUID, assistant_id: UUID, query: str,
                       *, top_k: int = MAX_RETRIEVAL_TOP_K) -> RetrievalResult:
        """Return only current chunks from the assistant's active ready index."""


_SNAPSHOT_SQL = text("""
-- knowledge_index_sources.source_sha256 identifies extracted text, not uploaded
-- file bytes. The file hash is separately included in the index manifest.
SELECT a.active_knowledge_index_id AS active_index_id,
       i.state AS index_state, i.embedding_provider, i.embedding_model,
       i.vector_dimension,
       EXISTS (
         SELECT 1 FROM public.knowledge_files f
          WHERE f.owner_id = a.owner_id AND f.assistant_id = a.id
            AND f.removed_at IS NULL AND f.processing_state IN ('accepted','processing')
       ) AS has_pending_files,
       EXISTS (
         SELECT 1 FROM public.knowledge_files f
         JOIN public.knowledge_file_text t
           ON t.file_id=f.id AND t.owner_id=f.owner_id AND t.assistant_id=f.assistant_id
          WHERE f.owner_id=a.owner_id AND f.assistant_id=a.id
            AND f.removed_at IS NULL AND f.processing_state='extracted'
       ) AS has_extracted_files,
       CASE WHEN a.active_knowledge_index_id IS NULL THEN FALSE ELSE
         EXISTS (SELECT 1 FROM public.knowledge_index_sources s
                  WHERE s.index_id=a.active_knowledge_index_id
                    AND s.owner_id=a.owner_id AND s.assistant_id=a.id)
         AND NOT EXISTS (
           SELECT 1 FROM public.knowledge_files f
           LEFT JOIN public.knowledge_file_text t
             ON t.file_id=f.id AND t.owner_id=f.owner_id AND t.assistant_id=f.assistant_id
           WHERE f.owner_id=a.owner_id AND f.assistant_id=a.id
             AND f.removed_at IS NULL AND f.processing_state='extracted'
             AND (t.file_id IS NULL OR NOT EXISTS (
               SELECT 1 FROM public.knowledge_index_sources s
                WHERE s.index_id=a.active_knowledge_index_id AND s.file_id=f.id
                  AND s.owner_id=f.owner_id AND s.assistant_id=f.assistant_id
                  AND s.extraction_version=t.extraction_version
                AND EXISTS (
                  SELECT 1 FROM public.knowledge_chunks c
                   WHERE c.index_id=s.index_id AND c.file_id=s.file_id
                     AND c.owner_id=s.owner_id AND c.assistant_id=s.assistant_id
                     AND c.extraction_version=s.extraction_version
                     AND c.source_sha256=s.source_sha256
                )
             ))
         ) AND NOT EXISTS (
           SELECT 1 FROM public.knowledge_index_sources s
            WHERE s.index_id=a.active_knowledge_index_id
              AND NOT EXISTS (
                SELECT 1 FROM public.knowledge_files f
                JOIN public.knowledge_file_text t
                  ON t.file_id=f.id AND t.owner_id=f.owner_id AND t.assistant_id=f.assistant_id
                WHERE f.id=s.file_id AND f.owner_id=a.owner_id AND f.assistant_id=a.id
                  AND f.removed_at IS NULL AND f.processing_state='extracted'
                  AND t.extraction_version=s.extraction_version
                  AND EXISTS (
                    SELECT 1 FROM public.knowledge_chunks c
                     WHERE c.index_id=s.index_id AND c.file_id=s.file_id
                       AND c.owner_id=s.owner_id AND c.assistant_id=s.assistant_id
                       AND c.extraction_version=s.extraction_version
                       AND c.source_sha256=s.source_sha256
                  )
              )
         ) END AS sources_match
  FROM public.assistants a
  LEFT JOIN public.knowledge_indexes i
    ON i.id=a.active_knowledge_index_id AND i.owner_id=a.owner_id AND i.assistant_id=a.id
 WHERE a.id=:assistant_id AND a.owner_id=:owner_id
""")


_SEARCH_SQL = text("""
-- Match the text fingerprint recorded by indexing on both source and chunks.
SELECT c.file_id, c.id AS chunk_id, f.original_filename AS filename,
       c.chunk_text AS chunk_text,
       1 - (c.embedding <=> CAST(:query_vector AS public.vector(768))) AS similarity,
       c.start_offset, c.end_offset, c.extraction_version
  FROM public.assistants a
  JOIN public.knowledge_indexes i
    ON i.id=a.active_knowledge_index_id AND i.assistant_id=a.id AND i.owner_id=a.owner_id
  JOIN public.knowledge_chunks c
    ON c.index_id=i.id AND c.assistant_id=i.assistant_id AND c.owner_id=i.owner_id
  JOIN public.knowledge_index_sources s
    ON s.index_id=c.index_id AND s.file_id=c.file_id
   AND s.assistant_id=c.assistant_id AND s.owner_id=c.owner_id
  JOIN public.knowledge_files f
    ON f.id=c.file_id AND f.assistant_id=c.assistant_id AND f.owner_id=c.owner_id
  JOIN public.knowledge_file_text t
    ON t.file_id=f.id AND t.assistant_id=f.assistant_id AND t.owner_id=f.owner_id
 WHERE a.id=:assistant_id AND a.owner_id=:owner_id
   AND a.active_knowledge_index_id=:index_id
   AND i.state='ready' AND i.embedding_provider=:embedding_provider
   AND i.embedding_model=:embedding_model AND i.vector_dimension=:dimension
   AND f.removed_at IS NULL AND f.processing_state='extracted'
   AND t.extraction_version=s.extraction_version
   AND c.extraction_version=s.extraction_version
   AND c.source_sha256=s.source_sha256
   AND 1 - (c.embedding <=> CAST(:query_vector AS public.vector(768))) >= :minimum_similarity
 ORDER BY c.embedding <=> CAST(:query_vector AS public.vector(768)), c.id
 LIMIT :top_k
""")


class PgVectorRetriever:
    """Exact cosine search, with owner identity set transaction-locally each time.

    `minimum_similarity` has no default: it must be supplied from the calibrated,
    deployment-configured threshold rather than an invented relevance value.
    """

    def __init__(self, sessions, embedding_provider: EmbeddingProvider, *,
                 minimum_similarity: float, embedding_provider_name: str = "openai",
                 embedding_model: str = "text-embedding-3-small", dimension: int = VECTOR_DIMENSION):
        if (isinstance(minimum_similarity, bool) or not isinstance(minimum_similarity, (int, float))
                or not math.isfinite(minimum_similarity) or not 0 <= minimum_similarity <= 1
                or dimension != VECTOR_DIMENSION or not embedding_provider_name or not embedding_model):
            raise RetrievalFailure("retrieval_configuration")
        self.sessions = sessions
        self.provider = embedding_provider
        self.minimum_similarity = float(minimum_similarity)
        self.provider_name = embedding_provider_name
        self.model = embedding_model
        self.dimension = dimension

    @staticmethod
    def _owner(session, owner_id: UUID) -> None:
        if session.bind.dialect.name == "postgresql":
            set_owner_identity(session, owner_id)

    def _snapshot(self, owner_id: UUID, assistant_id: UUID):
        try:
            with self.sessions.begin() as session:
                self._owner(session, owner_id)
                row = session.execute(_SNAPSHOT_SQL, {
                    "owner_id": owner_id, "assistant_id": assistant_id,
                }).mappings().one_or_none()
                return dict(row) if row is not None else None
        except SQLAlchemyError:
            raise RetrievalFailure("retrieval_unavailable") from None

    async def retrieve(self, owner_id: UUID, assistant_id: UUID, query: str,
                       *, top_k: int = MAX_RETRIEVAL_TOP_K) -> RetrievalResult:
        if (not isinstance(owner_id, UUID) or not isinstance(assistant_id, UUID)
                or not isinstance(query, str) or not query.strip() or len(query) > 4000
                or type(top_k) is not int or not 1 <= top_k <= MAX_RETRIEVAL_TOP_K):
            raise RetrievalFailure("retrieval_invalid_request")

        snapshot = self._snapshot(owner_id, assistant_id)
        if snapshot is None:
            raise RetrievalFailure("assistant_not_found")
        if snapshot["has_pending_files"]:
            raise RetrievalFailure("knowledge_not_ready")
        index_id = snapshot["active_index_id"]
        if index_id is None:
            return RetrievalResult("needs_preparation" if snapshot["has_extracted_files"] else "no_knowledge")
        if (snapshot["index_state"] != "ready" or not snapshot["sources_match"]
                or snapshot["embedding_provider"] != self.provider_name
                or snapshot["embedding_model"] != self.model
                or snapshot["vector_dimension"] != self.dimension):
            raise RetrievalFailure("knowledge_not_ready")

        try:
            embedded = await self.provider.embed((query,))
        except EmbeddingFailure:
            raise RetrievalFailure("embedding_unavailable") from None
        except Exception:
            # Adapter implementations are replaceable; raw errors never cross this boundary.
            raise RetrievalFailure("embedding_unavailable") from None
        if (embedded.model != self.model or embedded.dimensions != self.dimension
                or len(embedded.vectors) != 1):
            raise RetrievalFailure("embedding_space_mismatch")
        vector = embedded.vectors[0]
        if (len(vector) != self.dimension
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in vector)
                or math.hypot(*vector) == 0):
            raise RetrievalFailure("embedding_invalid_output")
        vector_literal = "[" + ",".join(repr(float(value)) for value in vector) + "]"

        try:
            with self.sessions.begin() as session:
                self._owner(session, owner_id)
                # Re-read readiness after provider I/O. A concurrent source/index
                # change must invalidate this query, not return stale evidence.
                current = session.execute(_SNAPSHOT_SQL, {
                    "owner_id": owner_id, "assistant_id": assistant_id,
                }).mappings().one_or_none()
                if (current is None or current["active_index_id"] != index_id
                        or current["index_state"] != "ready" or not current["sources_match"]
                        or current["has_pending_files"]
                        or current["embedding_provider"] != self.provider_name
                        or current["embedding_model"] != self.model
                        or current["vector_dimension"] != self.dimension):
                    raise RetrievalFailure("knowledge_not_ready")
                rows = session.execute(_SEARCH_SQL, {
                    "owner_id": owner_id, "assistant_id": assistant_id, "index_id": index_id,
                    "embedding_provider": self.provider_name, "embedding_model": self.model,
                    "dimension": self.dimension, "query_vector": vector_literal,
                    "minimum_similarity": self.minimum_similarity, "top_k": top_k,
                }).mappings().all()
        except RetrievalFailure:
            raise
        except SQLAlchemyError:
            raise RetrievalFailure("retrieval_unavailable") from None

        try:
            matches = tuple(RetrievedChunk(
                file_id=row["file_id"], chunk_id=row["chunk_id"], filename=row["filename"],
                text=row["chunk_text"], similarity=float(row["similarity"]),
                start_offset=row["start_offset"], end_offset=row["end_offset"],
                extraction_version=row["extraction_version"],
            ) for row in rows)
            if any(not math.isfinite(match.similarity) for match in matches):
                raise ValueError()
        except (KeyError, TypeError, ValueError, OverflowError):
            raise RetrievalFailure("retrieval_invalid_output") from None
        return RetrievalResult("matches" if matches else "no_relevant_chunks", matches, index_id)
