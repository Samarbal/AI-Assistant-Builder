import asyncio
import json
from types import SimpleNamespace
import pytest

from scripts import calibrate_live_retrieval as calibration_cli
from assistant_builder.calibration import CalibrationQuestion, calibrate_questions
from assistant_builder.embeddings import EmbeddingFailure, EmbeddingResult


class FakeProvider:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    async def embed(self, texts):
        self.calls.append(texts)
        if self.failure:
            raise self.failure
        vectors = tuple((float(index + 1),) + (0.0,) * 767 for index in range(7))
        return EmbeddingResult(vectors, "text-embedding-3-small", 768, 70, 70)


def questions():
    return tuple(
        CalibrationQuestion(
            f"Q{index + 1}", f"private fixture question {index + 1}",
            frozenset({f"expected-{index}"}) if index < 4 else frozenset(),
        )
        for index in range(7)
    )


def test_calibration_is_one_batch_and_reports_scores_without_fixture_text():
    provider = FakeProvider()
    progress = []

    def fetch(vector):
        index = int(vector[0]) - 1
        if index < 4:
            return ((f"expected-{index}", .80 + index * .01), ("distractor", .51))
        return (("unrelated", .30 + index * .01),)

    report = asyncio.run(calibrate_questions(
        questions(), provider, fetch, current_threshold=.534433, progress=progress.append,
    ))

    assert len(provider.calls) == 1
    assert len(provider.calls[0]) == 7
    assert report["request_count"] == 1
    assert report["dimensions"] == 768
    assert report["known_hits_at_current"] == 4
    assert report["unknown_false_positives_at_current"] == 0
    assert report["separation"] == "separable_on_fixtures"
    assert report["recommended_threshold"] == .58
    assert progress[0] == "embedding_started batch=7"
    assert progress[-1] == "scores_completed=7/7"
    serialized = str(report)
    assert "private fixture question" not in serialized
    assert "expected-0" not in serialized


def test_overlapping_scores_do_not_recommend_threshold():
    provider = FakeProvider()

    def fetch(vector):
        index = int(vector[0]) - 1
        return ((f"expected-{index}", .70),) if index < 4 else (("unrelated", .75),)

    report = asyncio.run(calibrate_questions(
        questions(), provider, fetch, current_threshold=.534433,
    ))
    assert report["separation"] == "no_safe_separation"
    assert report["recommended_threshold"] is None
    assert report["unknown_false_positives_at_current"] == 3


def test_provider_failure_is_sanitized_and_does_not_query_database():
    provider = FakeProvider(EmbeddingFailure("embedding_quota_or_rate_limited"))
    called = False

    def fetch(_vector):
        nonlocal called
        called = True
        return ()

    with pytest.raises(RuntimeError, match="calibration_provider_failure"):
        asyncio.run(calibrate_questions(questions(), provider, fetch, current_threshold=.5))
    assert not called


def test_invalid_fixture_is_rejected_before_provider_or_database():
    provider = FakeProvider()
    called = False

    def fetch(_vector):
        nonlocal called
        called = True
        return ()

    with pytest.raises(ValueError, match="calibration_fixture_invalid"):
        asyncio.run(calibrate_questions(questions()[:-1], provider, fetch, current_threshold=.5))
    assert provider.calls == []
    assert not called


def test_bad_database_scores_are_rejected():
    provider = FakeProvider()
    with pytest.raises(RuntimeError, match="calibration_query_invalid"):
        asyncio.run(calibrate_questions(
            questions(), provider, lambda _vector: (("bad", 1.5),), current_threshold=.5,
        ))


def test_threshold_decisions_use_full_precision_not_rounded_report_scores():
    provider = FakeProvider()

    def fetch(vector):
        index = int(vector[0]) - 1
        if index < 4:
            return ((f"expected-{index}", .5344334),)
        return (("unrelated", .4),)

    report = asyncio.run(calibrate_questions(
        questions(), provider, fetch, current_threshold=.534433,
    ))
    assert report["known_hits_at_current"] == 4
    assert report["questions"][0]["top5"][0]["similarity"] == .534433


def test_live_runner_uses_mock_provider_and_database_and_redacts_questions(tmp_path, monkeypatch, capsys):
    fixture_path = tmp_path / "fixture.json"
    fixture_data = {
        "owner_id": "00000000-0000-0000-0000-000000000001",
        "assistant_id": "00000000-0000-0000-0000-000000000002",
        "index_id": "00000000-0000-0000-0000-000000000003",
        "questions": [
            {"id": f"Q{i}", "text": f"private prompt {i}",
             "relevant_chunk_ids": [f"expected-{i}"] if i < 4 else []}
            for i in range(7)
        ],
    }
    fixture_path.write_text(json.dumps(fixture_data), encoding="utf-8")

    class FakeFactory:
        def __init__(self):
            self.query_count = 0

        def begin(self):
            factory = self

            class Transaction:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def execute(self, _statement, _params=None):
                    index = factory.query_count
                    factory.query_count += 1
                    chunk_id = f"expected-{index}" if index < 4 else f"unrelated-{index}"
                    score = .8 if index < 4 else .3
                    return SimpleNamespace(all=lambda: [SimpleNamespace(
                        chunk_id=chunk_id, similarity=score,
                    )])

            return Transaction()

    class FakeEngine:
        disposed = False

        def dispose(self):
            self.disposed = True

    factory = FakeFactory()
    engine = FakeEngine()
    provider = FakeProvider()
    monkeypatch.setattr(calibration_cli, "_preflight", lambda *_args: None)
    monkeypatch.setattr(calibration_cli, "get_settings", lambda: SimpleNamespace(
        retrieval_min_similarity=.534433, embedding_model="text-embedding-3-small",
    ))
    monkeypatch.setattr(calibration_cli, "create_database_engine", lambda: engine)
    monkeypatch.setattr(calibration_cli, "sessionmaker", lambda *_args, **_kwargs: factory)
    monkeypatch.setattr(calibration_cli, "set_owner_identity", lambda *_args: None)
    monkeypatch.setattr(calibration_cli, "OpenAIEmbeddingProvider", lambda _settings: provider)
    monkeypatch.setattr("sys.argv", ["calibrate_live_retrieval.py", "--fixture", str(fixture_path), "--live"])

    result = calibration_cli.main()
    assert result == 0
    captured = capsys.readouterr().out
    assert "CALIBRATION_REPORT" in captured
    assert "private prompt" not in captured
    assert len(provider.calls) == 1
    assert len(provider.calls[0]) == 7
    assert factory.query_count == 14  # seven read-only transaction settings plus seven score queries
    assert engine.disposed
