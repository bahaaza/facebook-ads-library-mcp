"""Offline tests for the Ad Library markdown parser and tool wiring.

Run:  python -m pytest tests/ -q
These do not hit the network — they exercise _parse_ad_library_markdown against a
fixture that mirrors the markdown crawl4ai produces for a rendered Ad Library page.
"""

import facebook_ads_mcp_complete as m

FIXTURE = """
Some header junk

Library ID: 111111111111111
Started running on Jan 5, 2026
**3 ads** use this creative
[Glyver](https://www.facebook.com/glyver/)
**Sponsored**
Automatiza tu operacion con IA. Agenda tu diagnostico gratis: [https://glyver.net](https://l.facebook.com/l.php?u=https%3A%2F%2Fglyver.net%2F&h=AbC)
[![creative](https://scontent.xx.fbcdn.net/v/photo.jpg) GLYVER.NET Agenda tu diagnostico Learn more ](https://l.facebook.com/l.php?u=https%3A%2F%2Fglyver.net%2F&h=AbC)
Facebook Instagram

Library ID: 222222222222222
Started running on Feb 16, 2026
[Otra Marca](https://www.facebook.com/otramarca/)
**Sponsored**
Prueba nuestro producto hoy.
[![creative](https://scontent.xx.fbcdn.net/v/photo2.jpg) OTRA Compra ahora Shop now ](https://l.facebook.com/l.php?u=https%3A%2F%2Fotramarca.com%2Fpromo)

Library ID: 111111111111111
(duplicate card re-rendered by infinite scroll — should be ignored)
[Glyver](https://www.facebook.com/glyver/)
"""


def _parsed():
    return m._parse_ad_library_markdown(FIXTURE)


def test_card_count_and_dedupe():
    ads = _parsed()
    assert len(ads) == 2
    assert [a["library_id"] for a in ads] == ["111111111111111", "222222222222222"]


def test_advertiser_and_dates():
    a = _parsed()[0]
    assert a["advertiser"] == "Glyver"
    assert a["advertiser_handle"] == "glyver"
    assert a["started_running"] == "Jan 5, 2026"
    assert a["ads_using_creative"] == 3


def test_landing_url_decoded():
    a = _parsed()[0]
    assert a["landing_url"] == "https://glyver.net/"
    assert a["landing_domain"] == "glyver.net"


def test_cta_and_link_text():
    a, b = _parsed()
    assert a["cta"] == "Learn more"
    assert a["link_text"] == "Agenda tu diagnostico"  # leading shouted domain dropped
    assert b["cta"] == "Shop now"


def test_body_strips_redirect_links():
    a = _parsed()[0]
    assert "l.facebook.com" not in a["body"]
    assert a["body"].startswith("Automatiza tu operacion con IA")


def test_ad_details_url():
    a = _parsed()[0]
    assert a["ad_details_url"] == "https://www.facebook.com/ads/library/?id=111111111111111"


def test_empty_input():
    assert m._parse_ad_library_markdown("") == []


def test_only_scraping_tools_are_registered():
    # The server is a pure Ad Library scraper — no ads_archive API tools.
    assert hasattr(m, "search_ad_library")
    assert hasattr(m, "scrape_ad_library_url")
    for gone in (
        "search_facebook_ads",
        "analyze_ad_performance_metrics",
        "generate_facebook_intelligence_report",
        "fb_api",
    ):
        assert not hasattr(m, gone), f"{gone} should have been removed"
