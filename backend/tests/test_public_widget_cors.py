from fastapi.testclient import TestClient

from assistant_builder.config import Settings
from assistant_builder.main import create_app


WIDGET_ORIGIN = "https://widget.example.test"


def client_for(monkeypatch, origin=WIDGET_ORIGIN):
    settings = Settings(_env_file=None, widget_asset_origin=origin)
    monkeypatch.setattr("assistant_builder.main.get_settings", lambda: settings)
    monkeypatch.setattr("assistant_builder.public_api.get_settings", lambda: settings)
    return TestClient(create_app())


def test_public_chat_preflight_allows_exact_widget_origin_and_required_headers(monkeypatch):
    with client_for(monkeypatch) as client:
        response = client.options("/public/assistants/00000000-0000-0000-0000-000000000001/conversations",
            headers={"Origin": WIDGET_ORIGIN, "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "content-type,x-demo-access,x-visitor-token"})
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == WIDGET_ORIGIN
    assert "x-demo-access" in response.headers["access-control-allow-headers"].lower()
    assert "x-visitor-token" in response.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in response.headers


def test_public_response_has_cors_only_for_exact_widget_origin(monkeypatch):
    with client_for(monkeypatch) as client:
        allowed = client.get("/public/assistants/00000000-0000-0000-0000-000000000001",
                             headers={"Origin": WIDGET_ORIGIN})
        rejected = client.get("/public/assistants/00000000-0000-0000-0000-000000000001",
                              headers={"Origin": "https://attacker.example.test"})
    assert allowed.status_code == 503  # public chat remains disabled
    assert allowed.headers["access-control-allow-origin"] == WIDGET_ORIGIN
    assert "access-control-allow-origin" not in rejected.headers


def test_preflight_rejects_other_origins_and_unapproved_headers(monkeypatch):
    with client_for(monkeypatch) as client:
        origin = client.options("/public/assistants/id/conversations",
            headers={"Origin": "https://attacker.example.test", "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "x-demo-access"})
        header = client.options("/public/assistants/id/conversations",
            headers={"Origin": WIDGET_ORIGIN, "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "authorization"})
    assert origin.status_code == 403
    assert header.status_code == 403


def test_owner_routes_do_not_receive_widget_cors(monkeypatch):
    with client_for(monkeypatch) as client:
        response = client.options("/assistants/00000000-0000-0000-0000-000000000001/publication",
            headers={"Origin": WIDGET_ORIGIN, "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "authorization"})
    assert response.status_code == 405
    assert "access-control-allow-origin" not in response.headers


def test_invalid_or_wildcard_widget_origin_fails_configuration(monkeypatch):
    for origin in ("*", "https://widget.example.test/path", "http://widget.example.test"):
        try:
            client_for(monkeypatch, origin)
        except ValueError as exc:
            assert "exact HTTPS origin" in str(exc)
        else:
            raise AssertionError("unsafe widget origin should fail closed")
