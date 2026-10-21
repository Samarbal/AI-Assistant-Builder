from dataclasses import replace
from uuid import UUID

import pytest

from assistant_builder.chunking import (
    ChunkingConfig, ChunkingError, ChunkingLimitExceeded, DeterministicChunker,
    SourceText, TiktokenTokenizer,
)


def source(text, file=3, extraction_version="pdf-docx-v1"):
    return SourceText(UUID(int=1), UUID(int=2), UUID(int=file), extraction_version, text)


@pytest.fixture(scope="module")
def tokenizer():
    return TiktokenTokenizer()


def assert_complete(chunks, document, tokenizer, size=600):
    assert chunks[0].start_offset == 0
    assert chunks[-1].end_offset == len(document.text)
    covered = 0
    previous_start = -1
    for ordinal, chunk in enumerate(chunks):
        chunk.validate_source(document)
        assert chunk.ordinal == ordinal
        assert previous_start < chunk.start_offset <= covered
        assert chunk.end_offset > covered
        assert chunk.token_count == len(tokenizer.encode(chunk.text)) <= size
        assert "\ufffd" not in chunk.text
        covered = chunk.end_offset
        previous_start = chunk.start_offset


@pytest.mark.parametrize("text", ["", " ", "\n\t"])
def test_empty_document_rejected(tokenizer, text):
    with pytest.raises(ChunkingError, match="Empty"):
        DeterministicChunker(tokenizer).chunk([source(text)])


def test_empty_corpus(tokenizer):
    assert DeterministicChunker(tokenizer).chunk([]) == ()


@pytest.mark.parametrize("text", [
    "English returns within fourteen days. " * 1000,
    "مدة التوصيل ثلاثة أيام عمل وسياسة الإرجاع أسبوعان. " * 500,
    "Delivery التوصيل 3 أيام 🚚 e\u0301 中文 👨‍👩‍👧‍👦\r\n" * 400,
    "<|endoftext|> is untrusted document text. " * 300,
    "🚀" * 2000,
], ids=["english", "arabic", "mixed-unicode", "special-token-text", "emoji"])
def test_unicode_mixed_long_documents_preserve_complete_source(tokenizer, text):
    document = source(text)
    chunks = DeterministicChunker(tokenizer).chunk([document])
    assert_complete(chunks, document, tokenizer)


@pytest.mark.parametrize("count,expected", [(599, 1), (600, 1), (601, 2), (1100, 2), (1101, 3)])
def test_exact_token_boundaries_and_overlap(tokenizer, count, expected):
    document = source(" hello" * count)
    assert len(tokenizer.encode(document.text)) == count
    chunks = DeterministicChunker(tokenizer).chunk([document])
    assert len(chunks) == expected
    assert_complete(chunks, document, tokenizer)
    for left, right in zip(chunks, chunks[1:]):
        overlap = document.text[right.start_offset:left.end_offset]
        assert len(tokenizer.encode(overlap)) == 100


def test_determinism_ordering_and_version_identity(tokenizer):
    first, second = source(" مرحبا Hello " * 200), source("Second file", file=4)
    chunker = DeterministicChunker(tokenizer)
    original = chunker.chunk([first, second])
    assert original == chunker.chunk([second, first])
    changed = chunker.chunk([replace(first, extraction_version="pdf-docx-v2"), second])
    assert original[0].text == changed[0].text
    assert original[0].id != changed[0].id
    assert changed[-1] == original[-1]
    assert original[0].id != chunker.chunk([replace(first, file_id=UUID(int=9))])[0].id
    assert original[0].id != DeterministicChunker(
        tokenizer, ChunkingConfig(overlap_tokens=99)).chunk([first])[0].id


def test_corpus_token_limit_is_aggregate(tokenizer):
    chunker = DeterministicChunker(tokenizer, ChunkingConfig(max_source_tokens=1000))
    assert chunker.chunk([source(" hi" * 500), source(" hi" * 500, file=4)])
    with pytest.raises(ChunkingLimitExceeded, match="source-token"):
        chunker.chunk([source(" hi" * 500), source(" hi" * 501, file=4)])


def test_production_token_limit(tokenizer):
    chunker = DeterministicChunker(tokenizer)
    chunks = chunker.chunk([source(" hi" * 100_000)])
    assert len(chunks) == 200
    with pytest.raises(ChunkingLimitExceeded, match="source-token"):
        chunker.chunk([source(" hi" * 100_001)])


def test_chunk_limit_aggregate_and_no_partial_result(tokenizer):
    chunker = DeterministicChunker(tokenizer, ChunkingConfig(max_chunks=2))
    with pytest.raises(ChunkingLimitExceeded, match="chunk-count"):
        chunker.chunk([source(" hi" * 1100), source("last", file=4)])
    assert len(chunker.chunk([source(" hi" * 1100)])) == 2


@pytest.mark.parametrize("changes", [
    {"start_offset": -1}, {"end_offset": 9999}, {"start_offset": 2, "end_offset": 1},
    {"text": "invented"}, {"file_id": UUID(int=8)}, {"extraction_version": "changed"},
])
def test_invalid_source_offsets_and_identity_rejected(tokenizer, changes):
    document = source("Original text")
    chunk = DeterministicChunker(tokenizer).chunk([document])[0]
    with pytest.raises(ChunkingError):
        replace(chunk, **changes).validate_source(document)


def test_bad_tokenizer_offsets_rejected(tokenizer):
    class Broken:
        fingerprint = "broken-test"
        encode = tokenizer.encode

        def offsets(self, tokens, text):
            return [len(text)] + [0] * len(tokens)

    with pytest.raises(ChunkingError, match="offsets"):
        DeterministicChunker(Broken()).chunk([source("hello world")])


@pytest.mark.parametrize("config", [
    {"chunk_tokens": 0}, {"overlap_tokens": 600}, {"overlap_tokens": -1},
    {"max_source_tokens": 100001}, {"max_chunks": 201}, {"chunk_tokens": True},
])
def test_invalid_config(config):
    with pytest.raises(ChunkingError):
        ChunkingConfig(**config)


def test_sources_cannot_mix_owners_assistants_or_duplicate_files(tokenizer):
    item = source("hello")
    for other in (item, replace(item, file_id=UUID(int=4), owner_id=UUID(int=8)),
                  replace(item, file_id=UUID(int=4), assistant_id=UUID(int=8))):
        with pytest.raises(ChunkingError):
            DeterministicChunker(tokenizer).chunk([item, other])


def test_invalid_unicode_and_bounded_text(tokenizer):
    with pytest.raises(ChunkingError, match="Unicode"):
        DeterministicChunker(tokenizer).chunk([source("invalid \ud800")])
    with pytest.raises(ChunkingLimitExceeded, match="extracted-text"):
        DeterministicChunker(tokenizer).chunk([source("x" * 2_000_001)])


def test_zero_overlap(tokenizer):
    document = source(" mixed مرحبا 🚀 " * 200)
    chunks = DeterministicChunker(tokenizer, ChunkingConfig(overlap_tokens=0)).chunk([document])
    assert_complete(chunks, document, tokenizer)
    assert "".join(c.text for c in chunks) == document.text
