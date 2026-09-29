import hashlib
import random
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from adwatch.config import settings
from adwatch.db import now
from adwatch.models import Ad, Alert, Competitor, Delivery, Scan, WorkerState


def enqueue(session, competitor_id: int) -> Scan:
    existing = session.scalar(
        select(Scan).where(
            Scan.competitor_id == competitor_id, Scan.status.in_(["queued", "running"])
        )
    )
    if existing:
        return existing
    # The database uniqueness constraint also protects concurrent API/worker requests.
    try:
        with session.begin_nested():
            scan = Scan(competitor_id=competitor_id)
            session.add(scan)
            session.flush()
        return scan
    except IntegrityError:
        return session.scalar(
            select(Scan).where(
                Scan.competitor_id == competitor_id, Scan.status.in_(["queued", "running"])
            )
        )


def alert(session, competitor, scan, kind: str, title: str, body: str):
    item = Alert(competitor_id=competitor.id, scan_id=scan.id, kind=kind, title=title, body=body)
    session.add(item)
    session.flush()
    for channel in settings().channels:
        session.add(Delivery(alert_id=item.id, channel=channel))


def creative_key(data: dict) -> str:
    # Copy grouping is a discovery aid, not proof of identical media or campaign identity.
    landing = urlsplit(data.get("landing_url") or "")
    fields = [
        data.get("body", ""),
        data.get("link_text", ""),
        data.get("cta", ""),
        urlunsplit((landing.scheme, landing.netloc, landing.path, "", "")),
    ]
    if not any(fields):
        fields = [str(data.get("library_id", ""))]
    return hashlib.sha256(
        "|".join(" ".join(str(v or "").split()).casefold() for v in fields).encode()
    ).hexdigest()


def finish_scan(session, scan: Scan, result: dict):
    competitor = session.get(Competitor, scan.competitor_id)
    timestamp = now()
    scan.finished_at = timestamp
    scan.lease_until = None
    competitor.last_scan_at = timestamp
    scan.evidence = result.get("markdown", "")[:100_000]
    if not result["success"]:
        scan.status = "failed"
        scan.error = result.get("error", "Ad Library unavailable")[:2000]
        if competitor.failures == 0:
            alert(
                session,
                competitor,
                scan,
                "scan_failed",
                f"Cannot scan {competitor.name}",
                "Monitoring is interrupted. Your saved ads are intact. " + scan.error,
            )
        competitor.failures += 1
        delay = min(24, 2 ** min(competitor.failures, 5))
        competitor.next_scan_at = timestamp + timedelta(hours=delay)
        return
    baseline = competitor.baseline_at is None
    new_items = []
    for data in result["ads"]:
        lid = str(data.get("library_id", ""))
        if not lid.isdigit():
            continue
        item = session.scalar(
            select(Ad).where(Ad.competitor_id == competitor.id, Ad.library_id == lid)
        )
        if item:
            item.last_seen = timestamp
            item.data = data
            item.creative_key = creative_key(data)
        else:
            item = Ad(
                competitor_id=competitor.id,
                library_id=lid,
                first_seen=timestamp,
                last_seen=timestamp,
                baseline=baseline,
                data=data,
                creative_key=creative_key(data),
            )
            session.add(item)
            # Flush so repeated IDs in the same render are deduplicated too.
            session.flush()
            if not baseline:
                new_items.append(item)
    scan.status = "succeeded"
    scan.ads_found = len({str(ad.get("library_id")) for ad in result["ads"]})
    scan.new_ads = len(new_items)
    scan.partial = result.get("partial", False)
    if competitor.failures:
        alert(
            session,
            competitor,
            scan,
            "scan_recovered",
            f"Scanning restored: {competitor.name}",
            "The Ad Library is readable again. Monitoring has resumed.",
        )
    competitor.failures = 0
    competitor.last_success_at = timestamp
    if baseline:
        competitor.baseline_at = timestamp
    elif new_items:
        links = "\n".join(
            f"• {item.data.get('link_text') or item.data.get('body', '')[:120] or item.library_id}\n"
            f"  https://www.facebook.com/ads/library/?id={item.library_id}"
            for item in new_items[:15]
        )
        alert(
            session,
            competitor,
            scan,
            "new_ads",
            f"{len(new_items)} new ads observed: {competitor.name}",
            f"Newly observed since your baseline (not necessarily newly launched).\n{links}",
        )
    competitor.next_scan_at = timestamp + timedelta(
        hours=competitor.interval_hours, seconds=random.randint(0, 300)
    )


def schedule_due(session):
    for competitor in session.scalars(
        select(Competitor).where(Competitor.enabled.is_(True), Competitor.next_scan_at <= now())
    ):
        enqueue(session, competitor.id)


def recover_expired(session):
    for scan in session.scalars(
        select(Scan).where(Scan.status == "running", Scan.lease_until <= now())
    ):
        finish_scan(
            session, scan, dict(success=False, error="Worker stopped before this scan completed.")
        )


def claim_scan(session) -> tuple[int, str] | None:
    from adwatch.scraper import build_url

    state = session.get(WorkerState, 1)
    if not state or state.next_browser_at > now():
        return None
    scan = session.scalar(
        select(Scan)
        .join(Competitor)
        .where(Scan.status == "queued", Competitor.enabled.is_(True))
        .order_by(Scan.queued_at)
        .with_for_update(skip_locked=True)
    )
    if not scan:
        return None
    competitor = session.get(Competitor, scan.competitor_id)
    scan.status = "running"
    scan.started_at = now()
    scan.lease_until = now() + timedelta(minutes=10)
    return scan.id, build_url(country=competitor.country, page_id=competitor.page_id)
