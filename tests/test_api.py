import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import adwatch.api as api
from adwatch.config import settings
from adwatch.db import Base, make_engine
from adwatch.models import Ad, Scan
from adwatch.service import creative_key


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "testing-password")
    settings.cache_clear()
    engine = make_engine(f"sqlite:///{tmp_path}/api.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def database():
        with factory() as session:
            yield session

    api.app.dependency_overrides[api.db] = database
    monkeypatch.setattr(api, "init_db", lambda: None)
    with TestClient(api.app) as c:
        c.auth = ("admin", "testing-password")
        c.factory = factory
        yield c
    api.app.dependency_overrides.clear()
    engine.dispose()
    settings.cache_clear()


def add(client):
    return client.post(
        "/api/competitors", json={"name": "Print Studio", "source": "12345", "country": "ALL"}
    )


def test_auth_and_origin(client):
    assert client.get("/api/overview", auth=("wrong", "wrong")).status_code == 401
    assert (
        client.post(
            "/api/competitors",
            headers={"Origin": "https://evil.test"},
            json={"name": "P", "source": "12345"},
        ).status_code
        == 403
    )
    assert client.get("/health", auth=("", "")).status_code == 200
    assert client.get("/api/overview").headers["X-Frame-Options"] == "DENY"


def test_watchlist_crud_queue_dedup_and_pause(client):
    response = add(client)
    assert response.status_code == 201
    item_id = response.json()["id"]
    assert add(client).status_code == 409
    first = client.post(f"/api/competitors/{item_id}/scan").json()
    second = client.post(f"/api/competitors/{item_id}/scan").json()
    assert first["id"] == second["id"]
    assert client.get("/api/competitors").json()[0]["last_scan"]["status"] == "queued"
    assert client.patch(f"/api/competitors/{item_id}", json={"enabled": False}).status_code == 200
    assert client.post(f"/api/competitors/{item_id}/scan").status_code == 409
    assert client.get("/api/scans").json()["items"][0]["status"] == "cancelled"
    assert (
        client.patch(f"/api/competitors/{item_id}", json={"interval_hours": 0}).status_code == 422
    )
    assert client.patch(f"/api/competitors/{item_id}", json={"name": None}).status_code == 422
    assert client.delete(f"/api/competitors/{item_id}").status_code == 204
    assert client.get("/api/scans").json()["items"] == []


def test_reject_broad_search_and_unsafe_source(client):
    assert (
        client.post(
            "/api/competitors",
            json={
                "name": "P",
                "source": "https://www.facebook.com.evil.test/ads/library/?view_all_page_id=123",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/competitors",
            json={"name": "P", "source": "https://www.facebook.com/ads/library/?q=foo"},
        ).status_code
        == 422
    )
    assert client.post("/api/competitors", json={"name": " ", "source": "123"}).status_code == 422


def test_ad_search_notes_and_csv_formula_escape(client):
    item_id = add(client).json()["id"]
    data = dict(
        library_id="123",
        body='=HYPERLINK("evil")',
        link_text="Personalized gift",
        landing_url="https://example.com",
    )
    with client.factory.begin() as s:
        ad = Ad(
            competitor_id=item_id,
            library_id="123",
            creative_key=creative_key(data),
            data=data,
            baseline=False,
        )
        s.add(ad)
        s.flush()
        ad_id = ad.id
    assert client.get("/api/ads?q=Personalized").json()["total"] == 1
    assert client.get("/api/ads?q=%").json()["total"] == 0
    assert (
        client.patch(
            f"/api/ads/{ad_id}", json={"saved": True, "notes": "Good gift angle"}
        ).status_code
        == 200
    )
    assert client.get("/api/ads?saved=true").json()["items"][0]["notes"] == "Good gift angle"
    assert "'=HYPERLINK" in client.get("/api/export.csv").text
    assert client.get("/api/ads?limit=201").status_code == 422
    with client.factory.begin() as s:
        scan = s.query(Scan).first()
        scan.evidence = "<script>alert(1)</script>"
        scan_id = scan.id
    evidence = client.get(f"/api/scans/{scan_id}/evidence")
    assert evidence.headers["content-type"].startswith("text/plain")


def test_search_decoded_arabic_and_hebrew(client):
    item_id = add(client).json()["id"]
    with client.factory.begin() as session:
        data = {"body": "هدايا مخصصة · מתנות אישיות", "link_text": "3D prints", "library_id": "456"}
        session.add(
            Ad(competitor_id=item_id, library_id="456", data=data, creative_key=creative_key(data))
        )
    assert client.get("/api/ads", params={"q": "هدايا"}).json()["total"] == 1
    assert client.get("/api/ads", params={"q": "מתנות"}).json()["total"] == 1


def test_anonymous_entry_and_form_session(client, tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text('<div id="root"></div>')
    monkeypatch.setattr(api, "STATIC", tmp_path)
    client.auth = None
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="root"' in response.text
    assert client.get("/api/overview").status_code == 401
    assert "www-authenticate" not in client.get("/api/session").headers
    wrong = client.post("/api/session", json={"username": "admin", "password": "wrong"})
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "Incorrect username or password"
    assert api.SESSION_COOKIE not in client.cookies
    response = client.post(
        "/api/session", json={"username": "admin", "password": "testing-password"}
    )
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Max-Age=28800" in cookie
    assert "testing-password" not in cookie
    assert client.get("/api/session").json() == {"authenticated": True}
    assert client.get("/api/overview").status_code == 200
    assert add(client).status_code == 201
    assert client.get("/api/export.csv").status_code == 200
    # Cookie sessions can perform same-origin writes but not cross-origin writes.
    assert (
        client.post(
            "/api/session",
            headers={"Origin": "https://evil.test"},
            json={"username": "admin", "password": "testing-password"},
        ).status_code
        == 403
    )
    assert client.delete("/api/session", headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.delete("/api/session").status_code == 204
    assert api.SESSION_COOKIE not in client.cookies
    assert client.get("/api/overview").status_code == 401
    assert client.get("/api/export.csv").status_code == 401


def test_session_tampering_expiry_and_rotation(client, monkeypatch):
    client.auth = None
    monkeypatch.setattr(api.time, "time", lambda: 1000000)
    response = client.post(
        "/api/session", json={"username": "admin", "password": "testing-password"}
    )
    token = response.cookies[api.SESSION_COOKIE]
    assert api.valid_session(token)
    assert not api.valid_session(token + "x")
    assert not api.valid_session("not.a.session")
    assert not api.valid_session("999999999999." + "a" * 32 + ".invalid")
    assert client.get("/api/overview", auth=("admin", "wrong")).status_code == 401
    monkeypatch.setattr(api.time, "time", lambda: 1000000 + api.SESSION_SECONDS)
    assert not api.valid_session(token)
    assert client.get("/api/overview").status_code == 401
    monkeypatch.setattr(api.time, "time", lambda: 1000000)
    monkeypatch.setenv("ADMIN_PASSWORD", "rotated-password")
    settings.cache_clear()
    assert not api.valid_session(token)
    assert client.get("/api/overview").status_code == 401


def test_https_session_cookie_is_secure(client):
    client.auth = None
    response = client.post(
        "https://testserver/api/session",
        json={"username": "admin", "password": "testing-password"},
    )
    assert response.status_code == 204
    assert "Secure" in response.headers["set-cookie"]


def test_test_email_auth_configuration_and_response(client, monkeypatch):
    calls = []
    monkeypatch.setattr(api, "send_test_email", lambda: calls.append("sent"))
    route = "/api/notifications/email/test"
    monkeypatch.setenv("SMTP_HOST", "")
    settings.cache_clear()
    assert client.post(route, auth=("wrong", "wrong")).status_code == 401
    assert client.post(route).status_code == 409
    assert calls == []
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "adwatch@example.test")
    monkeypatch.setenv("SMTP_TO", "owner@example.test")
    settings.cache_clear()
    assert client.post(route, headers={"Origin": "https://evil.test"}).status_code == 403
    assert calls == []
    result = client.post(route)
    assert result.status_code == 200
    assert "accepted by your mail server" in result.json()["message"]
    assert calls == ["sent"]


@pytest.mark.parametrize("error_kind", ["auth", "recipient", "connection"])
def test_test_email_errors_do_not_expose_secrets(client, monkeypatch, error_kind):
    import smtplib

    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "adwatch@example.test")
    monkeypatch.setenv("SMTP_TO", "owner@example.test")
    settings.cache_clear()
    errors = {
        "auth": smtplib.SMTPAuthenticationError(535, b"private password and account"),
        "recipient": smtplib.SMTPRecipientsRefused({"private@example.test": (550, b"no")}),
        "connection": OSError("private password and account"),
    }

    def fail():
        raise errors[error_kind]

    monkeypatch.setattr(api, "send_test_email", fail)
    result = client.post("/api/notifications/email/test")
    assert result.status_code == 502
    assert "private" not in result.text
    assert "check" in result.text.lower()
