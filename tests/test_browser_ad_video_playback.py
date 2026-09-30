"""Real decoded video playback against this checkout's production UI build."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import sessionmaker

from adwatch.db import make_engine
from adwatch.models import Ad
from adwatch.service import creative_key

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_BROWSER_TESTS"), reason="Set RUN_BROWSER_TESTS=1 after installing Chromium"
)
ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "tests" / "fixtures" / "adwatch-video-playback.webm"


@pytest.fixture(scope="module")
def video_server(tmp_path_factory):
    assert (ROOT / "web" / "dist" / "index.html").exists(), "Build this checkout's web UI first"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    database_url = f"sqlite:///{tmp_path_factory.mktemp('ad-video')}/video.db"
    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "video-test",
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
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    engine = None
    try:
        for _ in range(100):
            try:
                if httpx.get(url + "/health").status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            assert server.poll() is None, "UI server exited before startup"
            time.sleep(0.1)
        else:
            pytest.fail("UI server did not start")
        response = httpx.post(
            url + "/api/competitors",
            auth=("admin", "video-test"),
            json={"name": "Video Studio", "source": "123456"},
        )
        assert response.status_code == 201
        competitor_id = response.json()["id"]
        poster = url + "/assets/video-poster.svg"
        valid = url + "/assets/adwatch-fixture.webm"
        missing = url + "/assets/missing-video.webm"
        records = [
            (
                "Playable local video",
                {
                    "creative_video": valid,
                    "video_preview_image_url": poster,
                    "variants": [
                        {
                            "creative_video": valid,
                            "creative_image": poster,
                            "link_text": "Video variant",
                        }
                    ],
                },
            ),
            (
                "Playable public CDN video",
                {"creative_video": "https://video.xx.fbcdn.net/adwatch-fixture.webm"},
            ),
            ("Expired video", {"creative_video": missing, "creative_image": poster}),
            ("Preview only", {"video_preview_image_url": poster, "creative_image": poster}),
            (
                "Unsafe media",
                {
                    "creative_video": "javascript:alert('video')",
                    "creative_image": "data:image/svg+xml,<svg/>",
                },
            ),
            (
                "HD falls back to SD",
                {"creative_video": missing, "video_hd_url": missing, "video_sd_url": valid},
            ),
            ("Image only", {"creative_image": poster}),
            (
                "Mixed media",
                {
                    "creative_video": valid,
                    "creative_videos": [valid, "https://video.xx.fbcdn.net/adwatch-fixture.webm"],
                    "videos": [
                        {"creative_video": valid},
                        {"creative_video": "https://video.xx.fbcdn.net/adwatch-fixture.webm"},
                    ],
                    "creative_images": [poster, "https://image.xx.fbcdn.net/video-poster.svg"],
                    "started_running": "Jan 5, 2026",
                },
            ),
        ]
        engine = make_engine(database_url)
        with sessionmaker(engine).begin() as db:
            for index, (title, media) in enumerate(records, start=1):
                data = {
                    "link_text": title,
                    "body": f"Creative {index}",
                    "status": "active",
                    "ad_details_url": f"https://www.facebook.com/ads/library/?id={100 + index}",
                    **media,
                }
                db.add(
                    Ad(
                        competitor_id=competitor_id,
                        library_id=str(100 + index),
                        data=data,
                        creative_key=creative_key(data),
                        baseline=False,
                    )
                )
        yield url
    finally:
        server.terminate()
        server.wait(timeout=10)
        if engine:
            engine.dispose()


@pytest.fixture
def video_page(video_server):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context()
        response = context.request.post(
            video_server + "/api/session",
            data={
                "username": "admin",
                "password": "video-test",
            },
        )
        assert response.ok
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(
            "**/adwatch-fixture.webm",
            lambda route: route.fulfill(
                path=str(MEDIA),
                content_type="video/webm",
            ),
        )
        page.route("**/missing-video.webm", lambda route: route.fulfill(status=404, body="Expired"))
        page.route(
            "**/video-poster.svg",
            lambda route: route.fulfill(
                content_type="image/svg+xml",
                body='<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect width="160" height="90" fill="green"/></svg>',
            ),
        )
        page.goto(video_server)
        page.get_by_role("heading", name="Playable local video", exact=True).wait_for()
        yield page
        assert errors == []
        browser.close()


def card(page, title):
    return page.locator(".ad-card").filter(has=page.get_by_role("heading", name=title, exact=True))


def assert_playback(video):
    # Waiting for decoded frames catches codec failures that mere element checks miss.
    expect(video).to_have_js_property("paused", True)
    assert video.get_attribute("autoplay") is None
    assert video.get_attribute("controls") is not None
    video.evaluate("video => { video.muted = true; return video.play(); }")
    expect(video).to_have_js_property("paused", False)
    video.page.wait_for_function(
        "video => video.currentTime > 0.25 && video.readyState >= 2 && "
        "video.getVideoPlaybackQuality().totalVideoFrames > 0",
        arg=video.element_handle(),
    )
    assert video.evaluate("video => video.videoWidth") == 160


@pytest.mark.parametrize("title", ["Playable local video", "Playable public CDN video"])
def test_decoded_gallery_and_detail_playback_pauses_on_close(video_page, title):
    page = video_page
    gallery = card(page, title)
    gallery_video = gallery.locator("video")
    assert_playback(gallery_video)
    gallery.get_by_role("button", name="Details", exact=True).click()
    expect(gallery_video).to_have_js_property("paused", True)
    dialog = page.get_by_role("dialog")
    video = dialog.locator("video").first
    assert_playback(video)
    video.evaluate("video => { window.closedVideo = video; }")
    dialog.get_by_role("button", name="Close", exact=True).click()
    expect(dialog).to_have_count(0)
    assert page.evaluate("window.closedVideo.paused")
    # Reopening creates a fresh, paused player; carousel video is playable as well.
    gallery.get_by_role("button", name="Details", exact=True).click()
    expect(dialog.locator("video").first).to_have_js_property("paused", True)
    if title == "Playable local video":
        variant = dialog.locator("video[aria-label='Ad variant 1 video']")
        assert_playback(variant)
        variant.evaluate("video => { window.closedVariantVideo = video; }")
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        assert page.evaluate("window.closedVariantVideo.paused")


def test_video_failures_preview_safety_and_sd_fallback(video_page):
    page = video_page
    expired = card(page, "Expired video")
    expect(expired.get_by_text("Video could not be played", exact=True)).to_be_visible()
    expect(expired.get_by_role("link", name="Open original ad", exact=True)).to_have_attribute(
        "href",
        "https://www.facebook.com/ads/library/?id=103",
    )
    expect(expired.locator("video")).to_have_count(0)
    expired.get_by_role("button", name="Retry video", exact=True).click()
    expect(expired.get_by_text("Video could not be played", exact=True)).to_be_visible()
    expired.get_by_role("button", name="Details", exact=True).click()
    expect(
        page.get_by_role("dialog").get_by_text("Video could not be played", exact=True)
    ).to_be_visible()
    page.get_by_role("button", name="Close", exact=True).click()
    preview = card(page, "Preview only")
    expect(
        preview.get_by_text("Only a preview image was available for this video.")
    ).to_be_visible()
    expect(preview.locator("video")).to_have_count(0)
    expect(preview.get_by_role("img", name="Video preview", exact=True)).to_be_visible()
    unsafe = card(page, "Unsafe media")
    expect(unsafe.get_by_text("Video unavailable", exact=True)).to_be_visible()
    expect(unsafe.locator("video, img")).to_have_count(0)
    expect(unsafe.get_by_role("link", name="Open original ad")).to_have_attribute(
        "href", "https://www.facebook.com/ads/library/?id=105"
    )
    fallback_video = card(page, "HD falls back to SD").locator("video")
    expect(fallback_video).to_have_attribute(
        "src", page.url.rstrip("/") + "/assets/adwatch-fixture.webm"
    )
    assert_playback(fallback_video)
    image = card(page, "Image only")
    expect(image.get_by_role("img", name="Image only", exact=True)).to_be_visible()
    expect(image.locator("video")).to_have_count(0)


def test_mixed_media_keeps_all_videos_images_and_advertised_date(video_page):
    page = video_page
    mixed = card(page, "Mixed media")
    expect(mixed.locator(".ad-date time")).to_have_attribute("datetime", "2026-01-05")
    assert_playback(mixed.locator("video"))
    mixed.get_by_role("button", name="Details", exact=True).click()
    detail = page.get_by_role("dialog", name="Mixed media", exact=True)
    expect(detail.locator("video")).to_have_count(2)
    assert_playback(detail.locator("video").nth(1))
    detail.get_by_role("button", name="View image 1 of 2 for Mixed media", exact=True).click()
    viewer = page.get_by_role("dialog", name="Mixed media image viewer", exact=True)
    expect(viewer.get_by_text("Image 1 of 2", exact=True)).to_be_visible()
    page.keyboard.press("ArrowRight")
    image = viewer.locator("img")
    expect(image).to_have_attribute("src", "https://image.xx.fbcdn.net/video-poster.svg")
    page.wait_for_function("el => el.complete && el.naturalWidth > 0", arg=image.element_handle())
    page.keyboard.press("Escape")
    expect(detail).to_be_visible()
    expect(detail.locator(".ad-date time")).to_have_attribute("datetime", "2026-01-05")
    detail.get_by_role("button", name="Close", exact=True).click()
