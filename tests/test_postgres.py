"""Disposable PostgreSQL integration tests, including competing queue producers."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from adwatch.db import Base, make_engine, now
from adwatch.models import Ad, Alert, Competitor, Scan, WorkerState
from adwatch.service import claim_scan, enqueue, finish_scan, schedule_due

URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not URL, reason="Set TEST_POSTGRES_URL to a disposable test database"
)


@pytest.fixture
def pg():
    assert URL and URL.rsplit("/", 1)[-1].endswith("_test"), (
        "Use a disposable database ending in _test"
    )
    engine = make_engine(URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield engine, factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_parallel_enqueues_and_advisory_leadership(pg):
    engine, factory = pg
    with factory.begin() as session:
        c = Competitor(name="Print Studio", page_id="12345")
        session.add(c)
        session.flush()
        cid = c.id
    barrier = Barrier(2)

    def queue():
        with factory.begin() as session:
            barrier.wait()
            return enqueue(session, cid).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(queue) for _ in range(2)]
        ids = [f.result(timeout=20) for f in futures]
    assert ids[0] == ids[1]
    with engine.connect() as first, engine.connect() as second:
        assert first.scalar(text("SELECT pg_try_advisory_lock(719283041)"))
        assert not second.scalar(text("SELECT pg_try_advisory_lock(719283041)"))
        first.execute(text("SELECT pg_advisory_unlock(719283041)"))
        assert second.scalar(text("SELECT pg_try_advisory_lock(719283041)"))
        second.execute(text("SELECT pg_advisory_unlock(719283041)"))


def test_scheduled_scan_baseline_new_ad_and_persistence(pg):
    _, factory = pg
    with factory.begin() as session:
        c = Competitor(
            name="Print Studio", page_id="12345", next_scan_at=now() - timedelta(hours=1)
        )
        session.add_all([c, WorkerState(id=1, next_browser_at=now())])
        session.flush()
        cid = c.id
        schedule_due(session)
    with factory.begin() as session:
        first, _ = claim_scan(session)
    with factory.begin() as session:
        finish_scan(
            session,
            session.get(Scan, first),
            {"success": True, "ads": [{"library_id": "111", "body": "Custom keychains"}]},
        )
        session.get(Competitor, cid).next_scan_at = now() - timedelta(seconds=1)
    with factory.begin() as session:
        schedule_due(session)
        second, _ = claim_scan(session)
    with factory.begin() as session:
        finish_scan(
            session,
            session.get(Scan, second),
            {
                "success": True,
                "ads": [
                    {"library_id": "111", "body": "Custom keychains"},
                    {"library_id": "222", "body": "Event gifts"},
                ],
            },
        )
    # New sessions see committed history and exactly one new-ad event.
    with factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(Ad)) == 2
        assert session.scalar(select(func.count()).select_from(Alert)) == 1
        assert session.get(Scan, second).new_ads == 1
        session.delete(session.get(Competitor, cid))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Ad)) == 0
        assert session.scalar(select(func.count()).select_from(Scan)) == 0
        assert session.scalar(select(func.count()).select_from(Alert)) == 0
