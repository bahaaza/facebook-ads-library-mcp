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
