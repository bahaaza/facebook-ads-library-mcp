import pytest

from adwatch.parser import _decode_landing_url, _parse_ad_library_markdown
from adwatch.scraper import build_url, classify, page_id_from_source, validate_library_url


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/facebook.com/ads/library/",
        "https://www.facebook.com.evil.test/ads/library/",
        "https://www.facebook.com@127.0.0.1/ads/library/",
        "http://www.facebook.com/ads/library/",
        "https://www.facebook.com:8443/ads/library/",
        "https://www.facebook.com/ads/library/../other",
    ],
)
def test_reject_lookalike_and_non_library_urls(url):
    with pytest.raises(ValueError):
        validate_library_url(url)


def test_first_card_bold_id_and_full_date():
    ads = _parse_ad_library_markdown(
        "Library ID: 123\nStarted running on September 3, 2026\nActive\n**Sponsored**\nHello"
    )
    assert ads[0]["library_id"] == "123"
    assert ads[0]["started_running"] == "September 3, 2026"
    assert ads[0]["status"] == "active"
    assert _parse_ad_library_markdown("**Library ID:** 456\n")[0]["library_id"] == "456"


def test_decode_once_preserves_encoded_query():
    assert (
        _decode_landing_url(
            "https://l.facebook.com/l.php?u=https%3A%2F%2Fexample.com%2F%3Ftag%3Da%2526b"
        )
        == "https://example.com/?tag=a%26b"
    )


def test_unknown_or_blocked_is_not_empty_success():
    assert not classify("", 200)["success"]
    assert not classify("No results found\nLog in to continue", 200)["success"]
    assert not classify("No results found", 403)["success"]
    assert classify("No ads match your search criteria", 200)["outcome"] == "empty"
    assert classify("Library ID: 123\nActive", 403)["success"]


def test_page_source_and_build_url():
    assert page_id_from_source("12345") == "12345"
    assert (
        page_id_from_source("https://www.facebook.com/ads/library/?view_all_page_id=12345")
        == "12345"
    )
    with pytest.raises(ValueError):
        page_id_from_source("https://www.facebook.com/ads/library/?q=PrintStudio")
    assert "country=ALL" in build_url(page_id="12345")
    assert "q=3d+printing" in build_url(query="3d printing")
    with pytest.raises(ValueError):
        build_url(page_id="handle-not-an-id")


def test_current_markup_avatar_multiline_cta_and_neighbor_status():
    md = """Active

Library ID: 123
Started running on Sep 17, 2026
![Advertiser](https://scontent.xx.fbcdn.net/avatar.jpg)
[Print Studio](https://www.facebook.com/printstudio/)
**Sponsored**
Personalized keychains for your team.
[![](https://scontent.xx.fbcdn.net/creative.jpg)

EXAMPLE.COM

Custom event gifts

example.com

Shop Now](https://l.facebook.com/l.php?u=https%3A%2F%2Fexample.com%2F)

Inactive

Library ID: 456
[Print Studio](https://www.facebook.com/printstudio/)
**Sponsored**
Earlier campaign.
"""
    a, b = _parse_ad_library_markdown(md)
    assert a["creative_image"] == "https://scontent.xx.fbcdn.net/creative.jpg"
    assert a["cta"] == "Shop now"
    assert a["link_text"] == "Custom event gifts"
    assert a["status"] == "active"
    assert b["status"] == "inactive"
    assert a["body"] == "Personalized keychains for your team."


def test_later_snapshot_enriches_without_erasing_fields():
    md = "Library ID: 123\n[Print](https://www.facebook.com/print/)\n\nLibrary ID: 123\nStarted running on Sep 1, 2026\n**Sponsored**\nNow hydrated copy"
    ad = _parse_ad_library_markdown(md)[0]
    assert ad["advertiser"] == "Print"
    assert ad["body"] == "Now hydrated copy"
    assert ad["started_running"] == "Sep 1, 2026"


def test_empty_result_must_be_ui_evidence_not_a_phrase_in_copy():
    assert not classify("Our product prevents the dreaded No results found error.", 200)["success"]
