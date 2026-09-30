from datetime import timedelta

from sqlalchemy import func, select

from adwatch.db import now
from adwatch.models import Ad, Alert, Competitor, Scan, WorkerState
from adwatch.service import claim_scan, enqueue, finish_scan, recover_expired, schedule_due


def competitor(session):
    item = Competitor(name="Print Studio", page_id="123456", country="ALL")
    session.add(item)
    session.commit()
    return item


def complete(session, item, ids, success=True, partial=False):
    scan = enqueue(session, item.id)
    finish_scan(
        session,
        scan,
        dict(
            success=success,
            ads=[dict(library_id=id, body="Print your idea") for id in ids],
            partial=partial,
            error="Blocked",
        ),
    )
    session.commit()
    return scan


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_baseline_new_ids_duplicate_and_restart(db_session):
    c = competitor(db_session)
    complete(db_session, c, ["111", "111", "222"])
    assert count(db_session, Ad) == 2
    assert count(db_session, Alert) == 0
    db_session.expire_all()  # fresh DB reads, as on worker restart
    scan = complete(db_session, c, ["222", "333", "333"])
    assert scan.new_ads == 1
    assert count(db_session, Alert) == 1
    assert count(db_session, Ad) == 3
    complete(db_session, c, ["333", "111"])
    assert count(db_session, Alert) == 1
    # A missing ad remains in history; disappearance is not inactivity evidence.
    assert count(db_session, Ad) == 3


def test_empty_success_establishes_baseline(db_session):
    c = competitor(db_session)
    complete(db_session, c, [])
    assert c.baseline_at
    scan = complete(db_session, c, ["111"])
    assert scan.new_ads == 1


def test_failure_does_not_establish_or_reset_baseline(db_session):
    c = competitor(db_session)
    complete(db_session, c, [], success=False)
    assert c.baseline_at is None
    complete(db_session, c, [], success=False)
    assert count(db_session, Alert) == 1  # no failure spam
    assert c.failures == 2
    complete(db_session, c, ["111"])
    assert count(db_session, Ad) == 1
    assert db_session.scalar(select(Ad)).baseline
    assert c.failures == 0
    assert count(db_session, Alert) == 2  # recovery, no new-ad alert on baseline
    complete(db_session, c, [], success=False)
    assert count(db_session, Ad) == 1


def test_schedule_queue_dedup_and_paused(db_session):
    c = competitor(db_session)
    c.next_scan_at = now() - timedelta(hours=1)
    db_session.commit()
    schedule_due(db_session)
    schedule_due(db_session)
    db_session.commit()
    assert count(db_session, Scan) == 1
    assert enqueue(db_session, c.id).id == db_session.scalar(select(Scan)).id
    db_session.add(WorkerState(id=1, next_browser_at=now()))
    db_session.commit()
    c.enabled = False
    db_session.commit()
    assert claim_scan(db_session) is None
    c.enabled = True
    db_session.commit()
    claimed = claim_scan(db_session)
    assert claimed and "view_all_page_id=123456" in claimed[1]
    assert claim_scan(db_session) is None


def test_expired_worker_scan_fails_then_backoff(db_session):
    c = competitor(db_session)
    scan = enqueue(db_session, c.id)
    scan.status = "running"
    scan.lease_until = now() - timedelta(minutes=1)
    db_session.commit()
    recover_expired(db_session)
    db_session.commit()
    assert scan.status == "failed"
    assert c.failures == 1
    assert c.next_scan_at > now() + timedelta(hours=1)
    assert count(db_session, Alert) == 1


def test_partial_scan_keeps_coverage_warning(db_session):
    c = competitor(db_session)
    scan = complete(db_session, c, ["111"], partial=True)
    assert scan.partial
    assert c.baseline_at


def test_nullable_fields_do_not_break_history(db_session):
    from adwatch.service import creative_key

    assert creative_key({"library_id": "111", "body": None, "cta": None, "landing_url": None})
    assert creative_key({"library_id": "111"}) != creative_key({"library_id": "222"})
