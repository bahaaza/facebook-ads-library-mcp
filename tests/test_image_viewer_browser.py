"""Exercise image viewing in Chromium against this worktree's production UI."""

import os
import socket
import subprocess
import sys
import time

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

IMAGE_HOST = "https://image-fixture.fbcdn.net/"


@pytest.fixture
def image_dashboard(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    database_url = f"sqlite:///{tmp_path}/images.db"
    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "image-test",
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
    engine = make_engine(database_url)
    try:
        for _ in range(100):
            try:
                if httpx.get(url + "/health").status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            if server.poll() is not None:
                pytest.fail("Image UI server exited before startup")
            time.sleep(0.1)
        else:
            pytest.fail("Image UI server did not start")
        with sessionmaker(engine).begin() as db:
            competitor = Competitor(
                name="Image Studio", page_id="123", country="ALL", enabled=False
            )
            db.add(competitor)
            db.flush()
            creatives = [
                {"link_text": "Legacy portrait", "creative_image": IMAGE_HOST + "portrait.svg"},
                {
                    "link_text": "Image collection",
                    "creative_image": IMAGE_HOST + "first.svg",
                    "creative_images": [
                        IMAGE_HOST + "first.svg",
                        IMAGE_HOST + "wide.svg",
                        IMAGE_HOST + "broken.jpg",
                        "javascript:alert(1)",
                    ],
                    "variants": [
                        {"link_text": "Variant one", "creative_image": IMAGE_HOST + "wide.svg"},
                        {
                            "link_text": "Variant two",
                            "creative_images": [
                                IMAGE_HOST + "variant.svg",
                                IMAGE_HOST + "last.svg",
                            ],
                        },
                    ],
                },
                {"link_text": "Empty creative", "body": "No images"},
                {"link_text": "Only array", "creative_images": [IMAGE_HOST + "array.svg"]},
            ]
            for index, data in enumerate(creatives):
                data["body"] = data.get("body", data["link_text"])
                data["ad_details_url"] = f"https://www.facebook.com/ads/library/?id={100 + index}"
                db.add(
                    Ad(
                        competitor_id=competitor.id,
                        library_id=str(100 + index),
                        data=data,
                        creative_key=creative_key(data),
                    )
                )
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))

            def serve_image(route):
                if route.request.url.endswith("broken.jpg"):
                    route.fulfill(status=404, body="expired")
                else:
                    width, height = (300, 1800) if "portrait" in route.request.url else (2400, 400)
                    route.fulfill(
                        content_type="image/svg+xml",
                        body=f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><rect width="100%" height="100%" fill="#438c68"/></svg>',
                    )

            page.route(IMAGE_HOST + "**", serve_image)
            page.goto(url)
            page.get_by_label("Username", exact=True).fill("admin")
            page.get_by_label("Password", exact=True).fill("image-test")
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.get_by_role("button", name="Ad library", exact=True).click()
            page.get_by_role("heading", name="Image collection", exact=True).wait_for()
            yield page
            assert errors == []
            browser.close()
    finally:
        engine.dispose()
        server.terminate()
        server.wait(timeout=10)


def assert_contained(page, viewer):
    image = viewer.locator(".ad-image-stage img")
    expect(image).to_be_visible()
    page.wait_for_function("el => el.complete && el.naturalWidth > 0", arg=image.element_handle())
    assert image.evaluate("el => getComputedStyle(el).objectFit") == "contain"
    assert viewer.evaluate(
        "el => { const r = el.getBoundingClientRect(); return r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight; }"
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_legacy_single_image_containment_escape_and_focus(image_dashboard):
    page = image_dashboard
    trigger = page.get_by_role("button", name="View image for Legacy portrait", exact=True)
    trigger.click()
    viewer = page.get_by_role("dialog", name="Legacy portrait image viewer", exact=True)
    expect(viewer.get_by_text("Image 1 of 1", exact=True)).to_be_visible()
    expect(viewer.get_by_role("button", name="Next image", exact=True)).to_have_count(0)
    assert_contained(page, viewer)
    expect(viewer.get_by_role("link", name="Open original ad", exact=True)).to_have_attribute(
        "href", "https://www.facebook.com/ads/library/?id=100"
    )
    # The native modal traps focus even when cycling past the last control.
    viewer.get_by_role("link", name="Open original ad", exact=True).focus()
    page.keyboard.press("Tab")
    expect(viewer.get_by_role("button", name="Close image viewer", exact=True)).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(viewer.get_by_role("link", name="Open original ad", exact=True)).to_be_focused()
    page.keyboard.press("Escape")
    expect(viewer).to_have_count(0)
    expect(trigger).to_be_focused()
    assert page.evaluate("document.body.style.overflow") == ""


def test_collection_navigation_variants_failure_and_detail_restore(image_dashboard):
    page = image_dashboard
    trigger = page.get_by_role("button", name="View 5 images for Image collection", exact=True)
    trigger.click()
    viewer = page.get_by_role("dialog", name="Image collection image viewer", exact=True)
    expect(viewer.get_by_text("Image 1 of 5", exact=True)).to_be_visible()
    viewer.get_by_role("button", name="Next image", exact=True).click()
    expect(viewer.locator("img")).to_have_attribute("src", IMAGE_HOST + "wide.svg")
    assert_contained(page, viewer)
    page.keyboard.press("ArrowRight")
    expect(viewer.get_by_text("Image 3 of 5", exact=True)).to_be_visible()
    expect(viewer.get_by_text("Image unavailable", exact=True)).to_be_visible()
    expect(viewer.get_by_role("link", name="Open original ad", exact=True)).to_be_visible()
    page.keyboard.press("ArrowRight")
    expect(viewer.locator("img")).to_have_attribute("src", IMAGE_HOST + "variant.svg")
    page.keyboard.press("ArrowRight")
    expect(viewer.locator("img")).to_have_attribute("src", IMAGE_HOST + "last.svg")
    page.keyboard.press("ArrowRight")
    expect(viewer.get_by_text("Image 1 of 5", exact=True)).to_be_visible()
    viewer.get_by_role("button", name="Previous image", exact=True).click()
    expect(viewer.get_by_text("Image 5 of 5", exact=True)).to_be_visible()
    page.keyboard.press("ArrowLeft")
    expect(viewer.get_by_text("Image 4 of 5", exact=True)).to_be_visible()
    viewer.get_by_role("button", name="Close image viewer", exact=True).click()
    expect(trigger).to_be_focused()

    card = page.locator(".ad-card").filter(
        has=page.get_by_role("heading", name="Image collection", exact=True)
    )
    card.get_by_role("button", name="Details", exact=True).click()
    detail = page.get_by_role("dialog", name="Image collection", exact=True)
    thumbnail = detail.get_by_role(
        "button", name="View image 2 of 5 for Image collection", exact=True
    )
    thumbnail.click()
    expect(viewer.get_by_text("Image 2 of 5", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    expect(viewer).to_have_count(0)
    expect(detail).to_be_visible()
    expect(thumbnail).to_be_focused()
    # Arrays on a variant get their own navigable collection as well.
    detail.get_by_role("button", name="View image 2 of 2 for Ad variant 2", exact=True).click()
    variant = page.get_by_role("dialog", name="Ad variant 2 image viewer", exact=True)
    expect(variant.get_by_text("Image 2 of 2", exact=True)).to_be_visible()
    page.keyboard.press("ArrowLeft")
    expect(variant.locator("img")).to_have_attribute("src", IMAGE_HOST + "variant.svg")
    page.keyboard.press("Escape")
    expect(detail).to_be_visible()
    page.keyboard.press("Escape")
    expect(detail).to_have_count(0)


def test_mobile_array_only_and_no_image_detail(image_dashboard):
    page = image_dashboard
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="View image for Only array", exact=True).click()
    viewer = page.get_by_role("dialog", name="Only array image viewer", exact=True)
    assert_contained(page, viewer)
    page.keyboard.press("Escape")
    page.get_by_role("button", name="View 5 images for Image collection", exact=True).click()
    viewer = page.get_by_role("dialog", name="Image collection image viewer", exact=True)
    assert_contained(page, viewer)
    viewer.get_by_role("button", name="Next image", exact=True).click()
    assert_contained(page, viewer)
    viewer.get_by_role("button", name="Close image viewer", exact=True).click()
    page.get_by_role("button", name="View details for Empty creative", exact=True).click()
    expect(page.get_by_role("dialog", name="Empty creative", exact=True)).to_be_visible()
