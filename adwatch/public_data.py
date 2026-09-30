"""Read structured ad records already delivered to the anonymous public browser.

No direct GraphQL requests or authentication. Markup remains the fallback for MCP
keyword discovery; exact-Page monitoring requires verified advertiser identity.
"""

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from adwatch.parser import _decode_landing_url


def _text(value):
    if isinstance(value, dict):
        return str(value.get("text") or "")
    return value if isinstance(value, str) else ""


def _media(item):
    return next(
        (
            value
            for key in ("resized_image_url", "original_image_url", "video_preview_image_url")
            if isinstance(value := item.get(key), str) and value
        ),
        "",
    )


def extract_records(payload) -> list[dict]:
    result = {}
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(reversed(item))
            continue
        if not isinstance(item, dict):
            continue
        snapshot = item.get("snapshot")
        lid = str(item.get("ad_archive_id") or "")
        if not lid.isdigit() or not isinstance(snapshot, dict):
            stack.extend(reversed(list(item.values())))
            continue
        cards = [c for c in (snapshot.get("cards") or []) if isinstance(c, dict)]
        images = [c for c in (snapshot.get("images") or []) if isinstance(c, dict)]
        videos = [c for c in (snapshot.get("videos") or []) if isinstance(c, dict)]
        first = cards[0] if cards else {}
        creative_images = list(dict.fromkeys(_media(c) for c in images + cards if _media(c)))
        landing = _decode_landing_url(_text(snapshot.get("link_url") or first.get("link_url")))
        data = {
            "library_id": lid,
            "ad_details_url": f"https://www.facebook.com/ads/library/?id={lid}",
            "page_id": str(item.get("page_id") or snapshot.get("page_id") or ""),
            "advertiser": _text(snapshot.get("page_name") or item.get("page_name")),
            "advertiser_handle": urlparse(_text(snapshot.get("page_profile_uri"))).path.strip("/"),
            "body": _text(snapshot.get("body") or first.get("body")),
            "link_text": _text(snapshot.get("title") or first.get("title")),
            "cta": _text(snapshot.get("cta_text") or first.get("cta_text")),
            "landing_url": landing,
            "landing_domain": urlparse(landing).netloc,
            "creative_image": next((_media(c) for c in images + videos + cards if _media(c)), ""),
            "creative_images": creative_images,
            "platforms": [
                str(p).replace("_", " ").title() for p in (item.get("publisher_platform") or [])
            ],
            "status": "active"
            if item.get("is_active") is True
            else "inactive"
            if item.get("is_active") is False
            else "unknown",
            "ads_using_creative": item.get("collation_count"),
            "variant_count": len(cards),
            "variants": [
                {
                    "body": _text(c.get("body")),
                    "link_text": _text(c.get("title")),
                    "creative_image": _media(c),
                    "creative_images": [_media(c)] if _media(c) else [],
                    "landing_url": _text(c.get("link_url")),
                    "cta": _text(c.get("cta_text")),
                }
                for c in cards[:20]
            ],
        }
        timestamp = item.get("start_date")
        if isinstance(timestamp, (int, float)):
            try:
                data["started_running"] = datetime.fromtimestamp(timestamp, timezone.utc).strftime(
                    "%b %d, %Y"
                )
            except (ValueError, OverflowError, OSError):
                pass
        result[lid] = data
    return list(result.values())


def parse_payload(text: str) -> list[dict]:
    text = text.strip().removeprefix("for (;;);").strip()
    try:
        return extract_records(json.loads(text))
    except (ValueError, TypeError):
        # Incremental public GraphQL responses may have one JSON payload per line.
        result = []
        for line in text.splitlines():
            try:
                result.extend(extract_records(json.loads(line)))
            except (ValueError, TypeError):
                continue
        return result


def from_soup(soup: BeautifulSoup) -> list[dict]:
    result = []
    for script in soup.find_all("script", attrs={"type": "application/json"}):
        text = script.string or script.get_text()
        if "ad_archive_id" in text:
            result.extend(parse_payload(text))
    return result


def verified_empty_from_soup(soup: BeautifulSoup, page_id: str) -> bool:
    """Corroborate the rendered empty UI with a completed exact-Page search.

    Meta sometimes serves the functioning public app with an initial HTTP 403.
    Require its Page identity, query identity, and explicit final zero-result data;
    generic empty text in a blocked shell is not enough.
    """
    if not page_id or not any(
        urlparse(image.get("src", "")).path
        == "/images/ads/politics/archive/empty-state_overfiltering_3x.png"
        for image in soup.find_all("img")
    ):
        return False
    page_matches = query_matches = False
    connections = []
    for script in soup.find_all("script", attrs={"type": "application/json"}):
        try:
            stack = [json.loads(script.string or script.get_text())]
        except (ValueError, TypeError):
            continue
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("errors") or item.get("error"):
                return False
            if str(item.get("viewAllPageID", "")) == page_id:
                query_matches = True
            page = item.get("page")
            if isinstance(page, dict) and str(page.get("id", "")) == page_id:
                page_matches = True
            main = item.get("ad_library_main")
            if isinstance(main, dict) and "search_results_connection" in main:
                connections.append(main["search_results_connection"])
            stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
    return (
        page_matches
        and query_matches
        and bool(connections)
        and all(
            isinstance(connection, dict)
            and type(connection.get("count")) is int
            and connection["count"] == 0
            and connection.get("edges") == []
            and isinstance(connection.get("page_info"), dict)
            and connection["page_info"].get("has_next_page") is False
            for connection in connections
        )
    )


def combine(
    markdown_records: list[dict], structured: dict[str, dict], page_id: str = ""
) -> tuple[list[dict], int]:
    merged = {ad["library_id"]: ad for ad in structured.values()}
    for visible in markdown_records:
        item = {**merged.get(visible["library_id"], {})}
        # Rendered fields describe the visible variant; structured data supplies
        # identity, status, full copy (unless it is a dynamic template), and icons.
        item.update(
            {
                k: v
                for k, v in visible.items()
                if v and k not in {"page_id", "platforms", "status", "ads_using_creative"}
            }
        )
        metadata = structured.get(visible["library_id"], {})
        body = metadata.get("body", "")
        if body and "{{" not in body and len(body) > len(item.get("body", "")):
            item["body"] = body
        if not metadata:
            item.update({k: v for k, v in visible.items() if v})
        merged[visible["library_id"]] = item
    if page_id:
        matched = [ad for ad in merged.values() if ad.get("page_id") == page_id]
        return matched, len(merged) - len(matched)
    return list(merged.values()), 0
