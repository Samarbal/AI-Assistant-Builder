from types import SimpleNamespace

import pytest

from scripts.verify_phase3_playground_live import (
    SafeVerificationFailure,
    api_failure_code,
    require,
    set_stage,
)


def test_precondition_failure_reports_stage_and_safe_code():
    set_stage("assistant_ownership_and_index_readiness")
    with pytest.raises(SafeVerificationFailure) as raised:
        require(False, "Assistant is not owned by the authenticated test user")
    assert raised.value.stage == "assistant_ownership_and_index_readiness"
    assert raised.value.code == "Assistant is not owned by the authenticated test user"


def test_api_failure_exposes_only_allowlisted_code_not_private_response_text():
    response = SimpleNamespace(json=lambda: {
        "detail": {"code": "generation_rate_limited", "message": "private prompt and token"}
    })
    assert api_failure_code(response) == "generation_rate_limited"


def test_api_failure_rejects_unknown_or_malformed_codes():
    unknown = SimpleNamespace(json=lambda: {
        "detail": {"code": "private-response-text"}
    })
    malformed = SimpleNamespace(json=lambda: ["not an object"])
    invalid_json = SimpleNamespace(json=lambda: (_ for _ in ()).throw(ValueError()))
    assert api_failure_code(unknown) == "unknown"
    assert api_failure_code(malformed) == "unknown"
    assert api_failure_code(invalid_json) == "unknown"
