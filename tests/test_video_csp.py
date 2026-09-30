from fastapi.testclient import TestClient

from adwatch import api


def test_public_video_hosts_have_explicit_media_policy(monkeypatch, db_session):
    monkeypatch.setattr(api, "init_db", lambda: None)
    monkeypatch.setitem(api.app.dependency_overrides, api.db, lambda: db_session)
    with TestClient(api.app) as client:
        response = client.get("/health")
    directives = {
        parts[0]: parts[1:]
        for directive in response.headers["Content-Security-Policy"].split(";")
        if (parts := directive.split())
    }
    assert directives["media-src"] == ["'self'", "https://*.fbcdn.net", "https://*.facebook.com"]
    assert directives["script-src"] == ["'self'"]
    assert directives["connect-src"] == ["'self'"]
