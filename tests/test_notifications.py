import pytest
from sqlalchemy import select

from adwatch.config import settings
from adwatch.db import now
from adwatch.models import Alert, Competitor, Delivery, Scan
from adwatch.notifications import deliver_pending
from adwatch.service import finish_scan


def test_persistent_outbox_retries_and_no_duplicate_events(db_session, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "adwatch@example.test")
    monkeypatch.setenv("SMTP_TO", "owner@example.test")
    settings.cache_clear()
    c = Competitor(name="Print Studio", page_id="123")
    db_session.add(c)
    db_session.flush()
    scan = Scan(competitor_id=c.id)
    db_session.add(scan)
    db_session.flush()
    finish_scan(db_session, scan, dict(success=False, error="Blocked"))
    db_session.commit()
    assert len(db_session.scalars(select(Alert)).all()) == 1
    delivery = db_session.scalar(select(Delivery))
    assert delivery.channel == "email"

    def fail(*_):
        raise RuntimeError("credentials MUST NOT appear in DB")

    monkeypatch.setattr("adwatch.notifications.send", fail)
    for _ in range(5):
        delivery.next_attempt_at = now()
        db_session.commit()
        deliver_pending(db_session)
    assert delivery.status == "failed"
    assert delivery.attempts == 5
    assert "credentials" not in delivery.error
    assert delivery.sent_at is None
    monkeypatch.setattr("adwatch.notifications.send", lambda *_: None)
    delivery.status = "pending"
    delivery.attempts = 0
    delivery.next_attempt_at = now()
    db_session.commit()
    deliver_pending(db_session)
    assert delivery.status == "sent"
    assert delivery.sent_at
    settings.cache_clear()


@pytest.mark.parametrize("tls", ["starttls", "ssl"])
def test_test_email_uses_configured_transport_and_unique_messages(monkeypatch, tls):
    from adwatch import notifications

    for key, value in {
        "SMTP_HOST": "smtp.example.test",
        "SMTP_PORT": "587" if tls == "starttls" else "465",
        "SMTP_TLS": tls,
        "SMTP_USERNAME": "smtp-user",
        "SMTP_PASSWORD": "smtp-secret",
        "SMTP_FROM": "adwatch@example.test",
        "SMTP_TO": "one@example.test, two@example.test",
        "PUBLIC_URL": "http://localhost:18473",
    }.items():
        monkeypatch.setenv(key, value)
    settings.cache_clear()
    calls = []
    messages = []

    class SMTP:
        def __init__(self, host, port, **kwargs):
            calls.append(("connect", host, port, kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def starttls(self, **kwargs):
            assert kwargs["context"].check_hostname
            calls.append(("starttls",))

        def login(self, username, password):
            assert (username, password) == ("smtp-user", "smtp-secret")
            calls.append(("login",))

        def send_message(self, message):
            messages.append(message)
            return {}

    monkeypatch.setattr(notifications.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(notifications.smtplib, "SMTP_SSL", SMTP)
    try:
        notifications.send_test_email()
        notifications.send_test_email()
        assert len(messages) == 2
        assert messages[0]["Subject"] == "[Adwatch] Test email"
        assert messages[0]["To"] == "one@example.test, two@example.test"
        assert "http://localhost:18473" in messages[0].get_content()
        assert "smtp-secret" not in messages[0].as_string()
        assert messages[0]["Message-ID"] != messages[1]["Message-ID"]
        assert ("login",) in calls
        if tls == "starttls":
            assert ("starttls",) in calls
        else:
            assert calls[0][3]["context"].check_hostname
            assert ("starttls",) not in calls
    finally:
        settings.cache_clear()
