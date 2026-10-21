"""Independent embedding boundary. No persistence, retrieval, or generation imports."""
import asyncio
from dataclasses import dataclass, field
import json
import math
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from assistant_builder.chunking import TiktokenTokenizer
from assistant_builder.config import Settings


class EmbeddingFailure(Exception):
    """Only fixed safe codes; never include provider bodies or source text."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: tuple[tuple[float, ...], ...] = field(repr=False)
    model: str
    dimensions: int
    prompt_tokens: int
    total_tokens: int


class EmbeddingProvider(Protocol):
    async def embed(self, texts: tuple[str, ...]) -> EmbeddingResult:
        """One text or a bounded batch; output order always matches input order."""
        ...


class OpenAIEmbeddingProvider:
    def __init__(self, settings: Settings, *, transport=None):
        try:
            url = urlsplit(settings.embedding_base_url or "")
            if (url.scheme != "https" or url.hostname != "api.openai.com"
                    or url.port not in (None, 443) or url.username or url.password
                    or url.query or url.fragment or url.path.rstrip("/") != "/v1"
                    or not settings.embedding_api_key
                    or not settings.embedding_api_key.get_secret_value().strip()
                    or settings.embedding_model != "text-embedding-3-small"
                    or settings.embedding_dimension != 768):
                raise ValueError()
        except ValueError:
            raise EmbeddingFailure("embedding_configuration") from None
        self._url = settings.embedding_base_url.rstrip("/") + "/embeddings"
        self._key = settings.embedding_api_key
        self._model = settings.embedding_model
        self._dimension = settings.embedding_dimension
        self._timeout = settings.embedding_timeout_seconds
        self._batch_limit = settings.embedding_max_batch_size
        self._token_limit = settings.embedding_max_input_tokens
        self._transport = transport
        # Uses the existing cl100k_base implementation. Warm vocabulary cache at
        # bootstrap; initialization failure is configuration failure, not no data.
        try:
            self._tokenizer = TiktokenTokenizer()
        except Exception:
            raise EmbeddingFailure("embedding_configuration") from None

    async def embed(self, texts: tuple[str, ...]) -> EmbeddingResult:
        if not isinstance(texts, (tuple, list)) or not 1 <= len(texts) <= self._batch_limit:
            raise EmbeddingFailure("embedding_input_limit")
        # Character bound limits work before tokenization; no silent truncation.
        if any(not isinstance(t, str) or not t.strip() or len(t) > 32000 for t in texts):
            raise EmbeddingFailure("embedding_input_limit")
        texts = tuple(texts)
        try:
            for text in texts:
                text.encode("utf-8", errors="strict")
            count = sum(len(self._tokenizer.encode(t)) for t in texts)
        except (UnicodeError, ValueError):
            raise EmbeddingFailure("embedding_input_limit") from None
        if count > self._token_limit:
            raise EmbeddingFailure("embedding_input_limit")
        try:
            async with asyncio.timeout(self._timeout):
                async with httpx.AsyncClient(
                    transport=self._transport or httpx.AsyncHTTPTransport(retries=0),
                    follow_redirects=False, trust_env=False,
                    timeout=httpx.Timeout(self._timeout, connect=min(3, self._timeout))) as client:
                    async with client.stream("POST", self._url,
                        headers={"Authorization": "Bearer " + self._key.get_secret_value()},
                        json={"model": self._model, "input": texts,
                              "dimensions": self._dimension, "encoding_format": "float"}) as response:
                        errors = {401: "embedding_auth", 403: "embedding_auth",
                                  429: "embedding_quota_or_rate_limited",
                                  404: "embedding_model_unavailable"}
                        if response.status_code != 200:
                            raise EmbeddingFailure(errors.get(response.status_code, "embedding_unavailable"))
                        raw = bytearray()
                        async for part in response.aiter_bytes(chunk_size=8192):
                            raw.extend(part)
                            if len(raw) > 524288:
                                raise EmbeddingFailure("embedding_invalid_output")
            body = json.loads(raw)
            if body["model"] != self._model:
                raise ValueError()
            data = body["data"]
            if not isinstance(data, list) or len(data) != len(texts):
                raise ValueError()
            ordered = {}
            for item in data:
                index, vector = item["index"], item["embedding"]
                if type(index) is not int or not 0 <= index < len(texts) or index in ordered:
                    raise ValueError()
                if not isinstance(vector, list) or len(vector) != self._dimension:
                    raise EmbeddingFailure("embedding_dimension_mismatch")
                if any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
                    raise ValueError()
                norm = math.hypot(*vector)
                if not math.isfinite(norm) or norm == 0:
                    raise ValueError()
                ordered[index] = tuple(float(v) for v in vector)
            usage = body["usage"]
            prompt, total = usage["prompt_tokens"], usage["total_tokens"]
            if type(prompt) is not int or type(total) is not int or prompt != count or total != prompt:
                raise ValueError()
            return EmbeddingResult(tuple(ordered[i] for i in range(len(texts))),
                                   self._model, self._dimension, prompt, total)
        except (TimeoutError, httpx.TimeoutException):
            raise EmbeddingFailure("embedding_timeout") from None
        except httpx.HTTPError:
            raise EmbeddingFailure("embedding_unavailable") from None
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
            raise EmbeddingFailure("embedding_invalid_output") from None
