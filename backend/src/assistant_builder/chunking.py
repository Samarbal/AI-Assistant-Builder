"""Pure extracted-text chunking. No persistence, credentials or provider calls."""
from bisect import bisect_left
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version
import json
from typing import Protocol, Sequence
from uuid import UUID, NAMESPACE_URL, uuid5

import tiktoken


class ChunkingError(ValueError):
    """Invalid source/configuration or tokenizer contract."""


class ChunkingLimitExceeded(ChunkingError):
    """Reject the whole corpus; never return truncated knowledge."""


class Tokenizer(Protocol):
    fingerprint: str

    def encode(self, text: str) -> list[int]: ...

    def offsets(self, tokens: list[int], text: str) -> list[int]: ...


class TiktokenTokenizer:
    """Provisional local tokenizer, independent of any embedding API.

    Construct during explicit bootstrap: tiktoken may download public vocabulary
    on first initialization. Warm its cache before offline/runtime execution.
    No source text is sent to that vocabulary endpoint.
    """

    def __init__(self):
        self.encoding = tiktoken.get_encoding("cl100k_base")
        self.fingerprint = f"tiktoken:{version('tiktoken')}:cl100k_base"

    def encode(self, text: str) -> list[int]:
        # Documents containing special-token spellings are ordinary text.
        return self.encoding.encode_ordinary(text)

    def offsets(self, tokens: list[int], text: str) -> list[int]:
        decoded, offsets = self.encoding.decode_with_offsets(tokens)
        if decoded != text:
            raise ChunkingError("Tokenizer round-trip mismatch")
        return offsets + [len(text)]


@dataclass(frozen=True)
class SourceText:
    owner_id: UUID
    assistant_id: UUID
    file_id: UUID
    extraction_version: str
    text: str


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_tokens: int = 600
    overlap_tokens: int = 100
    max_source_tokens: int = 100_000
    max_chunks: int = 200

    def __post_init__(self):
        values = (self.chunk_tokens, self.overlap_tokens,
                  self.max_source_tokens, self.max_chunks)
        if any(type(value) is not int for value in values):
            raise ChunkingError("Limits must be integers")
        if not (8 <= self.chunk_tokens <= 600
                and 0 <= self.overlap_tokens < self.chunk_tokens
                and 1 <= self.max_source_tokens <= 100_000
                and 1 <= self.max_chunks <= 200):
            raise ChunkingError("Invalid chunking limits")


@dataclass(frozen=True)
class Chunk:
    id: UUID
    owner_id: UUID
    assistant_id: UUID
    file_id: UUID
    extraction_version: str
    source_sha256: str
    chunker_version: str
    ordinal: int
    start_offset: int
    end_offset: int
    token_count: int
    text: str

    def validate_source(self, source: SourceText):
        if ((self.owner_id, self.assistant_id, self.file_id, self.extraction_version)
                != (source.owner_id, source.assistant_id, source.file_id,
                    source.extraction_version)
                or not 0 <= self.start_offset < self.end_offset <= len(source.text)
                or source.text[self.start_offset:self.end_offset] != self.text
                or sha256(source.text.encode("utf-8")).hexdigest() != self.source_sha256):
            raise ChunkingError("Chunk does not match its source")


class Chunker(Protocol):
    def chunk(self, sources: Sequence[SourceText]) -> tuple[Chunk, ...]: ...


class DeterministicChunker:
    """600/100 token windows rounded to exact Unicode source boundaries.

    Offsets are Python Unicode code-point indices, end-exclusive (not UTF-16,
    UTF-8 bytes, PDF pages, or grapheme positions). Re-encode each actual slice
    because tokenization can change at a new boundary.
    """

    def __init__(self, tokenizer: Tokenizer, config: ChunkingConfig | None = None):
        self.tokenizer = tokenizer
        self.config = config or ChunkingConfig()
        self.fingerprint = (
            f"source-window-v1:{tokenizer.fingerprint}:"
            f"{self.config.chunk_tokens}:{self.config.overlap_tokens}"
        )

    def chunk(self, sources: Sequence[SourceText]) -> tuple[Chunk, ...]:
        if len(sources) > 5:
            raise ChunkingLimitExceeded("At most five source files")
        ordered = sorted(sources, key=lambda item: str(item.file_id))
        if len({s.file_id for s in ordered}) != len(ordered):
            raise ChunkingError("Duplicate source file")
        if len({(s.owner_id, s.assistant_id) for s in ordered}) > 1:
            raise ChunkingError("Sources must share an owner and assistant")
        total = 0
        prepared = []
        for source in ordered:
            if not all(isinstance(value, UUID) for value in (
                    source.owner_id, source.assistant_id, source.file_id)):
                raise ChunkingError("Source identifiers must be UUIDs")
            if not source.extraction_version.strip() or len(source.extraction_version) > 64:
                raise ChunkingError("Invalid extraction version")
            if not source.text.strip():
                raise ChunkingError("Empty extracted text")
            if len(source.text) > 2_000_000:
                raise ChunkingLimitExceeded("Phase 2 extracted-text limit exceeded")
            try:
                encoded = source.text.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                raise ChunkingError("Invalid Unicode source") from None
            tokens = self.tokenizer.encode(source.text)
            total += len(tokens)
            if total > self.config.max_source_tokens:
                raise ChunkingLimitExceeded("Corpus source-token limit exceeded")
            offsets = self.tokenizer.offsets(tokens, source.text)
            if (len(offsets) != len(tokens) + 1 or offsets[0] != 0
                    or offsets[-1] != len(source.text)
                    or any(type(o) is not int or o < 0 or o > len(source.text) for o in offsets)
                    or any(a > b for a, b in zip(offsets, offsets[1:]))):
                raise ChunkingError("Invalid tokenizer offsets")
            prepared.append((source, tokens, offsets, sha256(encoded).hexdigest()))

        result = []
        for source, tokens, offsets, digest in prepared:
            start_token = 0
            ordinal = 0
            while start_token < len(tokens):
                stop_token = min(start_token + self.config.chunk_tokens, len(tokens))
                start = offsets[start_token]
                # Unicode boundaries and slice retokenization can change counts.
                while stop_token > start_token:
                    end = offsets[stop_token]
                    text = source.text[start:end]
                    count = len(self.tokenizer.encode(text))
                    if end > start and count <= self.config.chunk_tokens:
                        break
                    stop_token -= 1
                else:
                    raise ChunkingError("No complete Unicode character fits the window")
                if len(result) >= self.config.max_chunks:
                    raise ChunkingLimitExceeded("Corpus chunk-count limit exceeded")
                identity = json.dumps([
                    str(source.owner_id), str(source.assistant_id), str(source.file_id),
                    source.extraction_version, digest, self.fingerprint, ordinal, start, end,
                ], ensure_ascii=True, separators=(",", ":"))
                result.append(Chunk(
                    uuid5(NAMESPACE_URL, identity), source.owner_id, source.assistant_id,
                    source.file_id, source.extraction_version, digest, self.fingerprint,
                    ordinal, start, end, count, text))
                ordinal += 1
                if end == len(source.text):
                    break
                candidate = max(start_token + 1, stop_token - self.config.overlap_tokens)
                # First token for a character avoids treating split UTF-8 bytes as text.
                candidate = bisect_left(offsets, offsets[candidate])
                if offsets[candidate] <= start:
                    candidate = bisect_left(offsets, end)
                start_token = candidate
        return tuple(result)
