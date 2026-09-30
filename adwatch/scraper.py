"""Bounded, anonymous browser scans. An unreadable page never means zero ads."""

import asyncio
import re
from urllib.parse import parse_qs, urlencode, urlparse

from bs4 import BeautifulSoup
from markdownify import markdownify

from adwatch.parser import _parse_ad_library_markdown
from adwatch.public_data import combine, from_soup, parse_payload, verified_empty_from_soup

BASE = "https://www.facebook.com/ads/library/"


def validate_library_url(url: str) -> str:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.facebook.com", "facebook.com"}
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path.rstrip("/") != "/ads/library"
    ):
        raise ValueError("Use an https://www.facebook.com/ads/library/ URL.")
    return url


def build_url(
    query: str = "",
    country: str = "ALL",
    page_id: str = "",
    active_status: str = "active",
    media_type: str = "all",
    ad_type: str = "all",
) -> str:
    if not query.strip() and not page_id:
        raise ValueError("Pass a query or a numeric advertiser Page ID.")
    if page_id and not re.fullmatch(r"\d{1,30}", page_id):
        raise ValueError("Advertiser Page ID must be numeric.")
    country = country.upper()
    if not re.fullmatch(r"[A-Z]{2}|ALL", country):
        raise ValueError("Country must be a two-letter ISO code or ALL.")
    if active_status not in {"active", "inactive", "all"}:
        raise ValueError("Invalid active_status.")
    if media_type not in {"all", "image", "meme", "video", "none"}:
        raise ValueError("Invalid media_type.")
    if ad_type not in {
        "all",
        "political_and_issue_ads",
        "employment_ads",
        "housing_ads",
        "financial_products_and_services_ads",
    }:
        raise ValueError("Invalid ad_type.")
    params = dict(
        active_status=active_status,
        ad_type=ad_type,
        country=country,
        media_type=media_type,
        search_type="page" if page_id else "keyword_unordered",
        locale="en_US",
    )
    if page_id:
        params["view_all_page_id"] = page_id
    elif query:
        params["q"] = query.strip()
    return BASE + "?" + urlencode(params)


def page_id_from_source(source: str) -> str:
    if re.fullmatch(r"\d{1,30}", source.strip()):
        return source.strip()
    validate_library_url(source)
    page_id = parse_qs(urlparse(source).query).get("view_all_page_id", [""])[0]
    if not re.fullmatch(r"\d{1,30}", page_id):
        raise ValueError(
            "Paste a Page's 'See all ads' link (view_all_page_id), or its numeric Page ID."
        )
    return page_id


def classify(
    markdown: str,
    status_code: int | None,
    truncated: bool = False,
    verified_empty: bool = False,
) -> dict:
    ads = _parse_ad_library_markdown(markdown)
    if ads:
        return dict(success=True, outcome="ok", ads=ads, partial=truncated)
    # Require explicit UI evidence, not merely absence of cards or an HTTP status.
    no_results = re.search(
        r"^\s*(?:No ads match your search criteria|No results found|There are no ads to show)\.?\s*$",
        markdown,
        re.IGNORECASE | re.MULTILINE,
    )
    blocked = re.search(
        r"captcha|temporarily blocked|log in to continue|unusual activity|access denied",
        markdown,
        re.IGNORECASE,
    )
    status_allows_empty = status_code not in (401, 403, 429) or (
        status_code == 403 and verified_empty
    )
    if no_results and not blocked and status_allows_empty:
        return dict(success=True, outcome="empty", ads=[], partial=False)
    return dict(
        success=False,
        outcome="unavailable",
        ads=[],
        partial=False,
        error=(
            "Ad Library could not be read"
            + (f" (HTTP {status_code})" if status_code is not None else "")
            + ". It may be blocked, still loading, or its layout changed."
        ),
    )


async def render(url: str, wait_seconds: int = 8, scroll_rounds: int = 8) -> dict:
    validate_library_url(url)
    if not 0 <= scroll_rounds <= 30 or not 3 <= wait_seconds <= 30:
        raise ValueError("wait_seconds must be 3–30 and scroll_rounds 0–30.")
    requested_page = parse_qs(urlparse(url).query).get("view_all_page_id", [""])[0]
    from playwright.async_api import async_playwright

    async with asyncio.timeout(180):
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    locale="en-US", viewport={"width": 1400, "height": 1600}
                )
                page = await context.new_page()
                structured = {}
                captures = set()
                from playwright.async_api import Error as BrowserError

                async def capture(response):
                    if "/api/graphql" not in response.url:
                        return
                    try:
                        for ad in parse_payload(await response.text()):
                            structured[ad["library_id"]] = ad
                    except (BrowserError, ValueError):
                        return

                def on_response(response):
                    task = asyncio.create_task(capture(response))
                    captures.add(task)
                    task.add_done_callback(captures.discard)

                page.on("response", on_response)
                response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(wait_seconds * 1000)
                # Public consent prompt, when present. No login or session cookies supplied.
                for label in ("Decline optional cookies", "Only allow essential cookies"):
                    button = page.get_by_role("button", name=label, exact=True)
                    if await button.count():
                        await button.first.click(timeout=5000)
                        await page.wait_for_timeout(1000)
                        break
                stable = 0
                previous = ""
                snapshots = []
                verified_empty = False

                # Collect every viewport: virtualized lists can remove earlier cards.
                async def snapshot():
                    nonlocal verified_empty
                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")
                    text = await page.locator("body").inner_text()
                    verified_empty = (
                        parse_qs(urlparse(page.url).query).get("view_all_page_id", [""])[0]
                        == requested_page
                        and verified_empty_from_soup(soup, requested_page)
                        and bool(
                            re.search(
                                r"^\s*No ads match your search criteria\.?\s*$",
                                text,
                                re.IGNORECASE | re.MULTILINE,
                            )
                        )
                    )
                    for ad in from_soup(soup):
                        structured.setdefault(ad["library_id"], ad)
                    for hidden in soup(["script", "style", "noscript", "head"]):
                        hidden.decompose()
                    md = markdownify(str(soup), heading_style="ATX")
                    snapshots.append(md)
                    return text

                previous = await snapshot()
                for _ in range(scroll_rounds):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(2500)
                    text = await snapshot()
                    stable = stable + 1 if text == previous else 0
                    previous = text
                    if stable >= 2:
                        break
                if captures:
                    await asyncio.gather(*captures)
                md = "\n\n".join(snapshots)
                status = response.status if response else None
                outcome = classify(md, status, truncated=stable < 2, verified_empty=verified_empty)
                records, excluded = combine(outcome["ads"], structured, requested_page)
                if records:
                    outcome = dict(
                        success=True, outcome="ok", ads=records, partial=stable < 2 or excluded > 0
                    )
                elif outcome["ads"] and requested_page:
                    outcome = dict(
                        success=False,
                        outcome="unavailable",
                        ads=[],
                        partial=False,
                        error="The rendered ads could not be verified against the requested Page ID.",
                    )
                return dict(
                    markdown=md, status_code=status, excluded_unverified=excluded, **outcome
                )
            finally:
                await browser.close()


async def scrape(url: str, wait_seconds: int = 8, scroll_rounds: int = 8) -> dict:
    try:
        return await render(url, wait_seconds, scroll_rounds)
    except Exception as exc:
        return dict(
            success=False,
            outcome="unavailable",
            ads=[],
            partial=False,
            error=f"{type(exc).__name__}: {str(exc)[:500]}",
            markdown="",
            status_code=None,
        )
