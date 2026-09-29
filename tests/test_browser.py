"""Real Chromium regression tests; all Facebook requests use controlled HTML fixtures."""

import asyncio
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from playwright.async_api import Browser
from playwright.sync_api import sync_playwright
from sqlalchemy.orm import sessionmaker

from adwatch.db import make_engine
from adwatch.models import Ad
from adwatch.service import creative_key

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_BROWSER_TESTS"), reason="Set RUN_BROWSER_TESTS=1 after installing Chromium"
)


def test_render_retains_virtualized_cards(monkeypatch):
    from adwatch.scraper import render

    original = Browser.new_context
    html = """<html><body><div id="cards" style="height:2000px">
    <p>Library ID: 111</p><a href="https://www.facebook.com/printstudio/">Print Studio</a>
    <b>Sponsored</b><p>First creative</p></div>
    <script>window.addEventListener('scroll', () => {
      if (window.scrollY > 0) document.getElementById('cards').innerHTML =
      '<p>Library ID: 222</p><b>Sponsored</b><p>Second creative</p>';
    });</script></body></html>"""

    async def context(self, **kwargs):
        ctx = await original(self, **kwargs)
        await ctx.route(
            "**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html)
        )
        return ctx

    monkeypatch.setattr(Browser, "new_context", context)
    result = asyncio.run(render("https://www.facebook.com/ads/library/?q=printing", 3, 4))
    assert result["success"]
    assert [ad["library_id"] for ad in result["ads"]] == ["111", "222"]
    assert not result["partial"]


def test_dashboard_workflows_and_mobile(tmp_path):
    # Serve the real production build with an isolated SQLite database. No user data.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    database_url = f"sqlite:///{tmp_path}/browser.db"
    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "browser-test",
        "PUBLIC_URL": url,
        "SMTP_HOST": "",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
    }
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "adwatch.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                if httpx.get(url + "/health").status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            if server.poll() is not None:
                pytest.fail("UI server exited before startup")
            time.sleep(0.1)
        errors = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context()
            page = context.new_page()
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(url)
            page.get_by_role("heading", name="Sign in to Adwatch", exact=True).wait_for()
            page.get_by_label("Username", exact=True).fill("admin")
            page.get_by_label("Password", exact=True).fill("wrong-password")
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.get_by_role("alert").get_by_text("Incorrect username or password").wait_for()
            page.get_by_label("Password", exact=True).fill("browser-test")
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.get_by_role("heading", name="Your radar starts here").wait_for()
            page.reload()
            page.get_by_role("heading", name="Your radar starts here").wait_for()
            page.get_by_role("button", name="Add your first competitor").click()
            page.get_by_label("Competitor name", exact=True).fill("Print Studio")
            page.get_by_label("Ad Library link or numeric Page ID").fill("123456")
            page.get_by_role("button", name="Start monitoring").click()
            page.get_by_role("heading", name="Print Studio", exact=True).wait_for()
            page.get_by_role("button", name="Pause", exact=True).click()
            page.get_by_text("Paused", exact=True).first.wait_for()
            page.get_by_role("button", name="Edit", exact=True).click()
            page.get_by_label("Hours between checks").fill("6")
            page.get_by_role("button", name="Save changes").click()
            page.get_by_text("Every 6h", exact=True).wait_for()
            engine = make_engine(database_url)
            session = sessionmaker(engine)
            with session.begin() as db:
                data = {
                    "body": "Make personalized gifts for your next event.",
                    "link_text": "Custom keychains",
                    "ad_details_url": "https://www.facebook.com/ads/library/?id=111",
                    "landing_url": "https://example.com",
                    "status": "active",
                }
                db.add(
                    Ad(
                        competitor_id=1,
                        library_id="111",
                        data=data,
                        creative_key=creative_key(data),
                        baseline=False,
                    )
                )
            page.get_by_role("button", name="Ad library", exact=True).click()
            page.get_by_role("heading", name="Custom keychains", exact=True).wait_for()
            page.get_by_role("button", name="Save ad", exact=True).click()
            page.get_by_role("button", name="Unsave ad", exact=True).wait_for()
            page.get_by_role("button", name="Details", exact=True).click()
            page.get_by_label("Your notes", exact=True).fill("Try an event bundle offer")
            page.get_by_role("button", name="Save notes", exact=True).click()
            page.get_by_role("button", name="Close", exact=True).click()
            page.get_by_placeholder("Search copy, headlines, destinations…").fill("not-present")
            page.get_by_role("heading", name="No ads in this view yet").wait_for()
            page.get_by_placeholder("Search copy, headlines, destinations…").fill("personalized")
            page.get_by_role("heading", name="Custom keychains", exact=True).wait_for()
            page.get_by_role("button", name="Settings & delivery", exact=True).click()
            page.get_by_role("heading", name="Alert delivery", exact=True).wait_for()
            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="Ad library", exact=True).click()
            page.get_by_role("heading", name="Custom keychains", exact=True).wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.set_viewport_size({"width": 1440, "height": 1000})
            if os.getenv("SCREENSHOT_PATH"):
                page.screenshot(path=os.environ["SCREENSHOT_PATH"], full_page=True)
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.get_by_role("heading", name="Sign in to Adwatch", exact=True).wait_for()
            page.reload()
            page.get_by_role("heading", name="Sign in to Adwatch", exact=True).wait_for()
            assert errors == []
            context.close()
            browser.close()
            engine.dispose()
    finally:
        server.terminate()
        server.wait(timeout=10)


def test_exact_page_scan_uses_public_response_identity(monkeypatch):
    from adwatch.scraper import render

    RECORD = {
        "ad_archive_id": "111",
        "page_id": "123",
        "is_active": True,
        "snapshot": {"page_name": "Print Studio", "body": {"text": "Custom gifts"}},
    }
    import json

    original = Browser.new_context
    other = {**RECORD, "ad_archive_id": "222", "page_id": "999"}
    payload = json.dumps({"data": {"records": [RECORD, other]}})
    html = '<html><body><p>Library ID: 111</p><p>Library ID: 222</p><script>fetch("/api/graphql/")</script></body></html>'

    async def context(self, **kwargs):
        ctx = await original(self, **kwargs)

        async def route(request):
            if "/api/graphql/" in request.request.url:
                await request.fulfill(status=200, content_type="application/json", body=payload)
            else:
                await request.fulfill(status=403, content_type="text/html", body=html)

        await ctx.route("**/*", route)
        return ctx

    monkeypatch.setattr(Browser, "new_context", context)
    result = asyncio.run(render("https://www.facebook.com/ads/library/?view_all_page_id=123", 3, 0))
    assert result["success"]
    assert [ad["library_id"] for ad in result["ads"]] == ["111"]
    assert result["ads"][0]["page_id"] == "123"
    assert result["excluded_unverified"] == 1
    assert result["partial"]
