"""Offline adapter tests: no credential files or live API calls."""
import asyncio
import json

import httpx
import pytest

from assistant_builder.chunking import TiktokenTokenizer
from assistant_builder.config import Settings
from assistant_builder.embeddings import EmbeddingFailure, OpenAIEmbeddingProvider


def settings(**updates):
    return Settings(_env_file=None, **dict({"embedding_base_url": "https://api.openai.com/v1",
        "embedding_api_key": "embedding-secret", "embedding_model": "text-embedding-3-small",
        "ai_api_key": "groq-secret", "ai_model": "openai/gpt-oss-20b"}, **updates))


def handler(req):
    assert str(req.url) == "https://api.openai.com/v1/embeddings"
    assert req.headers["Authorization"] == "Bearer embedding-secret"
    payload = json.loads(req.content)
    assert payload["model"] == "text-embedding-3-small"
    assert payload["dimensions"] == 768
    assert payload["encoding_format"] == "float"
    tokens = sum(len(TiktokenTokenizer().encode(t)) for t in payload["input"])
    return httpx.Response(200, json={"model": payload["model"],
        "data": [{"index": i, "embedding": [float(i + 1)] * 768}
                 for i in reversed(range(len(payload["input"])))],
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens}})


def run(callback=handler, texts=("Hello",), **config):
    adapter = OpenAIEmbeddingProvider(settings(**config), transport=httpx.MockTransport(callback))
    return asyncio.run(adapter.embed(texts))


@pytest.mark.parametrize("texts", [("Hello",), ("مرحبا",), ("Hello مرحبا",),
                                   ("English", "العربية", "Mixed عربي"), ("same", "same")])
def test_ordered_results(texts, caplog):
    output = run(texts=texts)
    assert len(output.vectors) == len(texts)
    assert [v[0] for v in output.vectors] == list(range(1, len(texts) + 1))
    assert all(len(v) == 768 for v in output.vectors)
    assert output.prompt_tokens == sum(len(TiktokenTokenizer().encode(t)) for t in texts)
    assert "embedding-secret" not in caplog.text
    assert "groq-secret" not in caplog.text
    assert "vectors=" not in repr(output)


@pytest.mark.parametrize("status,code", [(401,"embedding_auth"),(403,"embedding_auth"),
    (429,"embedding_quota_or_rate_limited"),(404,"embedding_model_unavailable"),
    (500,"embedding_unavailable"),(302,"embedding_unavailable")])
def test_provider_errors_one_attempt(status, code):
    calls = []
    def bad(req):
        calls.append(req)
        return httpx.Response(status, text="embedding-secret PRIVATE", headers={"Location": "https://other.test"})
    with pytest.raises(EmbeddingFailure, match=code):
        run(bad)
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["missing", "duplicate", "out_of_range", "boolean_index", "dimension",
    "nan", "inf", "zero", "string", "boolean_vector", "usage", "model"])
def test_malformed_response(change):
    def bad(req):
        body = handler(req).json()
        item = body["data"][0]
        if change == "missing": body["data"].pop()
        if change == "duplicate": body["data"][1]["index"] = item["index"]
        if change == "out_of_range": item["index"] = 2
        if change == "boolean_index": item["index"] = True
        if change == "dimension": item["embedding"].pop()
        if change in ("nan", "inf"): item["embedding"][0] = float(change)
        if change == "zero": item["embedding"] = [0] * 768
        if change == "string": item["embedding"][0] = "1"
        if change == "boolean_vector": item["embedding"][0] = True
        if change == "usage": body["usage"]["total_tokens"] += 1
        if change == "model": body["model"] = "other"
        # json.dumps permits NaN/Infinity to exercise defensive parsing.
        return httpx.Response(200, content=json.dumps(body))
    code = "embedding_dimension_mismatch" if change == "dimension" else "embedding_invalid_output"
    with pytest.raises(EmbeddingFailure, match=code):
        run(bad, texts=("one", "two"))


@pytest.mark.parametrize("texts", [(), ("",), (" ",), ("x",)*9, ("x"*32001,), (123,), ("\ud800",), "text"])
def test_bad_input_no_network(texts):
    def never(req):
        pytest.fail("No request allowed")
    with pytest.raises(EmbeddingFailure, match="embedding_input_limit"):
        run(never, texts=texts)


def test_token_limit_and_batch_limit():
    with pytest.raises(EmbeddingFailure, match="embedding_input_limit"):
        run(texts=("one two three",), embedding_max_input_tokens=1)
    with pytest.raises(EmbeddingFailure, match="embedding_input_limit"):
        run(texts=("one", "two"), embedding_max_batch_size=1)
    assert len(run(texts=("one",)*8).vectors) == 8


def test_deadline():
    async def slow(req):
        await asyncio.sleep(0.1)
        return handler(req)
    with pytest.raises(EmbeddingFailure, match="embedding_timeout"):
        run(slow, embedding_timeout_seconds=0.01)


@pytest.mark.parametrize("body", ["[]", "{}", "private-not-json", "x"*524289],
                         ids=["array", "missing", "invalid", "oversized"])
def test_invalid_envelope(body):
    with pytest.raises(EmbeddingFailure, match="embedding_invalid_output"):
        run(lambda req: httpx.Response(200, text=body))


@pytest.mark.parametrize("url", ["http://api.openai.com/v1", "https://other.test/v1",
                                "https://secret@api.openai.com/v1", "https://api.openai.com/v1?secret=x"])
def test_config_allowlist(url):
    with pytest.raises(EmbeddingFailure, match="embedding_configuration"):
        OpenAIEmbeddingProvider(settings(embedding_base_url=url))


def test_no_generation_key_fallback():
    with pytest.raises(EmbeddingFailure, match="embedding_configuration"):
        OpenAIEmbeddingProvider(settings(embedding_api_key=None))
    assert "embedding-secret" not in settings().model_dump_json()
