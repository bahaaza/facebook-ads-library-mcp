"""Durable scheduler + browser worker, independent of API/UI uptime."""

import asyncio
import logging
import signal
import time
from datetime import timedelta

from sqlalchemy import text

from adwatch.config import settings
from adwatch.db import Session, engine, init_db, now
from adwatch.models import Scan, WorkerState
from adwatch.notifications import deliver_pending
from adwatch.scraper import scrape
from adwatch.service import claim_scan, finish_scan, recover_expired, schedule_due

logger = logging.getLogger("adwatch.worker")


def tick() -> bool:
    with Session.begin() as session:
        state = session.get(WorkerState, 1)
        if not state:
            state = WorkerState(id=1)
            session.add(state)
        state.heartbeat_at = now()
        recover_expired(session)
        schedule_due(session)
        claimed = claim_scan(session)
    with Session() as session:
        deliver_pending(session)
    if not claimed:
        return False
    scan_id, url = claimed
    logger.info("Starting scan %s", scan_id)
    result = asyncio.run(scrape(url))
    with Session.begin() as session:
        scan = session.get(Scan, scan_id)
        # Competitor may have been removed while Chromium was reading the page.
        if scan and scan.status == "running":
            finish_scan(session, scan, result)
        state = session.get(WorkerState, 1)
        state.heartbeat_at = now()
        state.next_browser_at = now() + timedelta(seconds=settings().scan_gap_seconds)
    with Session() as session:
        deliver_pending(session)
    logger.info("Finished scan %s: %s", scan_id, result.get("outcome", "unavailable"))
    return True


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # Hold a session-scoped advisory lock on a dedicated connection. This prevents
    # duplicate schedulers/outbox senders if a second worker is accidentally started.
    with engine.connect() as leader:
        if engine.dialect.name == "postgresql":
            while not stopping:
                if leader.scalar(text("SELECT pg_try_advisory_lock(719283041)")):
                    break
                time.sleep(settings().poll_seconds)
        elif engine.dialect.name != "sqlite":
            raise RuntimeError("Unsupported database")
        while not stopping:
            # Loss of the dedicated connection loses leadership. Exit so Docker
            # restarts and elects a leader again, rather than continuing unguarded.
            leader.execute(text("SELECT 1"))
            try:
                tick()
            except Exception:
                logger.exception("Worker iteration failed")
            time.sleep(settings().poll_seconds)


if __name__ == "__main__":
    main()
