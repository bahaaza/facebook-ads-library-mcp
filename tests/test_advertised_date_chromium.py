"""Advertised dates in the production UI, backed by the real API and isolated data."""

import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import sessionmaker

from adwatch.db import make_engine
from adwatch.models import Ad, Competitor
from adwatch.service import creative_key

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_BROWSER_TESTS"), reason="Set RUN_BROWSER_TESTS=1 after installing Chromium"
)

ROOT = Path(__file__).resolve().parents[1]
# Include dates the platform supplies, strict ISO dates, and values Date.parse would
# silently normalize or interpret ambiguously. None means no trustworthy start date.
CASES = [
    ("short-meta", "Jan 5, 2026", "2026-01-05", "Jan 5, 2026"),
    ("long-meta", "September 3, 2026", "2026-09-03", "Sep 3, 2026"),
    ("padded-meta", "Sep 01, 2026", "2026-09-01", "Sep 1, 2026"),
    ("trimmed-meta", "  Sept 3, 2026  ", "2026-09-03", "Sep 3, 2026"),
    ("iso", "2026-08-24", "2026-08-24", "Aug 24, 2026"),
    ("leap-day", "2024-02-29", "2024-02-29", "Feb 29, 2024"),
    ("missing", None, None, None),
    ("null", None, None, None),
    ("empty", "", None, None),
    ("whitespace", "  ", None, None),
    ("invalid-text", "not a date", None, None),
    ("invalid-type", 1770000000, None, None),
    ("invalid-english-day", "February 30, 2026", None, None),
    ("invalid-short-month-day", "Apr 31, 2026", None, None),
    ("invalid-iso-day", "2026-02-30", None, None),
    ("non-leap-day", "2026-02-29", None, None),
    ("invalid-month", "2026-13-03", None, None),
    ("invalid-month-name", "Janu 5, 2026", None, None),
    ("ambiguous-numeric", "01/05/2026", None, None),
    ("missing-year", "Jan 5", None, None),
]


@pytest.fixture(scope="module")
def advertised_date_server(tmp_path_factory):
    assert (ROOT / "web/dist/index.html").exists(), "Build this worktree's UI with npm run build"
    directory = tmp_path_factory.mktemp("advertised-date-browser")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    database_url = f"sqlite:///{directory}/ads.db"
    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "date-browser-test",
        "PUBLIC_URL": url,
        "SMTP_HOST": "",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "adwatch.api:app", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    engine = make_engine(database_url)
    try:
        for _ in range(100):
            try:
                if httpx.get(url + "/health", timeout=1).status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            assert server.poll() is None, "Production UI server exited during startup"
            time.sleep(0.1)
        else:
            pytest.fail("Production UI server did not become healthy")
        with sessionmaker(engine).begin() as db:
            competitor = Competitor(name="Date fixtures", page_id="123", enabled=False)
            db.add(competitor)
            db.flush()
            for index, (name, started, _, _) in enumerate(CASES):
                data = {
                    "link_text": name,
                    "body": f"Date fixture {name}",
                    "started_running": started,
                    "ad_details_url": f"https://www.facebook.com/ads/library/?id={index + 100}",
                }
                # A truly absent field is different from null and exercises the fallback too.
                if name == "missing":
                    del data["started_running"]
                db.add(
                    Ad(
                        competitor_id=competitor.id,
                        library_id=str(index + 100),
                        data=data,
                        creative_key=creative_key(data),
                        first_seen=datetime(2026, 9, 30, 14, 45),
                        last_seen=datetime(2026, 9, 30, 14, 45),
                    )
                )
        yield url
    finally:
        server.terminate()
        server.wait(timeout=10)
        engine.dispose()


@pytest.fixture(scope="module")
def chromium():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def date_page(chromium, advertised_date_server):
    # A negative UTC offset must never shift Meta's calendar date to the prior day.
    context = chromium.new_context(locale="en-US", timezone_id="America/Los_Angeles")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(advertised_date_server)
    page.get_by_label("Username", exact=True).fill("admin")
    page.get_by_label("Password", exact=True).fill("date-browser-test")
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.locator(".ad-card")).to_have_count(len(CASES))
    yield page
    context.close()
    assert errors == []


@pytest.mark.parametrize("name,started,iso,label", CASES, ids=[case[0] for case in CASES])
def test_advertised_date_card_and_details(date_page, name, started, iso, label):
    page = date_page
    card = page.locator(".ad-card").filter(has=page.get_by_role("heading", name=name, exact=True))
    advertised = card.locator(".ad-date")
    expect(advertised).to_be_visible()
    if iso:
        expect(advertised).to_have_text(f"Advertised since{label}")
        expect(advertised.locator("time")).to_have_attribute("datetime", iso)
        expect(advertised.locator("time")).to_have_text(label)
    else:
        expect(advertised).to_have_text("Advertised date unavailable")
        expect(advertised.locator("time")).to_have_count(0)
    # The observation date remains explicit and never fills in a missing start date.
    expect(card.locator(".ad-footer")).to_contain_text("First observed Sep 30")
    expect(advertised).not_to_contain_text("Sep 30")

    card.get_by_role("button", name="Details", exact=True).click()
    dialog = page.get_by_role("dialog")
    detail_date = dialog.locator(".ad-date")
    expect(detail_date).to_be_visible()
    if iso:
        expect(detail_date).to_have_text(f"Advertised since{label}")
        expect(detail_date.locator("time")).to_have_attribute("datetime", iso)
    else:
        expect(detail_date).to_have_text("Advertised date unavailable")
        expect(detail_date.locator("time")).to_have_count(0)
    expect(dialog.locator(".detail-info")).to_contain_text("First observed Sep 30")
    expect(detail_date).not_to_contain_text("Sep 30")
    dialog.get_by_role("button", name="Close", exact=True).click()


def test_every_gallery_card_has_date_on_mobile(date_page):
    page = date_page
    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator(".ad-card .ad-date")).to_have_count(len(CASES))
    expect(page.locator(".ad-card .ad-date time")).to_have_count(6)
    for advertised in page.locator(".ad-card .ad-date").all():
        expect(advertised).to_be_visible()
        assert advertised.evaluate("el => el.scrollWidth <= el.clientWidth")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    card = page.locator(".ad-card").filter(
        has=page.get_by_role("heading", name="long-meta", exact=True)
    )
    card.get_by_role("button", name="Details", exact=True).click()
    expect(page.get_by_role("dialog").locator(".ad-date time")).to_have_text("Sep 3, 2026")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
