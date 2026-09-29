"""Backwards-compatible MCP tools, using the same bounded scraper as Adwatch."""

from collections import Counter

from fastmcp import FastMCP

from adwatch.parser import _decode_landing_url, _parse_ad_library_markdown  # noqa: F401
from adwatch.scraper import build_url, scrape, validate_library_url

mcp = FastMCP("Facebook Ad Library")


async def _render_ad_library(url: str, wait_seconds: int = 8, scroll_rounds: int = 8) -> dict:
    return await scrape(url, wait_seconds, scroll_rounds)


def _result(url: str, rendered: dict) -> dict:
    advertisers = dict(Counter(ad.get("advertiser", "unknown") for ad in rendered["ads"]))
    markdown = rendered.pop("markdown", "")
    return {
        **rendered,
        "url": url,
        "total_ads_parsed": len(rendered["ads"]),
        "advertisers": advertisers,
        "total_advertisers": len(advertisers),
        "raw_markdown": markdown[:16000],
    }


@mcp.tool(
    description="Search public Ad Library ads by keyword or numeric Page ID. No account/token."
)
async def search_ad_library(
    query: str = "",
    country: str = "MX",
    active_status: str = "active",
    media_type: str = "all",
    ad_type: str = "all",
    advertiser_page_id: str = "",
    wait_seconds: int = 8,
    scroll_rounds: int = 8,
) -> dict:
    try:
        url = build_url(query, country, advertiser_page_id, active_status, media_type, ad_type)
        result = _result(url, await _render_ad_library(url, wait_seconds, scroll_rounds))
        return {
            **result,
            "query": query or f"page_id:{advertiser_page_id}",
            "country": country,
            "scroll_rounds": scroll_rounds,
        }
    except ValueError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool(description="Read a public Facebook Ad Library URL and return structured ad cards.")
async def scrape_ad_library_url(url: str, wait_seconds: int = 8, scroll_rounds: int = 8) -> dict:
    try:
        validate_library_url(url)
        return _result(url, await _render_ad_library(url, wait_seconds, scroll_rounds))
    except ValueError as exc:
        return {"success": False, "error": str(exc)}


if __name__ == "__main__":
    # stdout belongs exclusively to MCP JSON-RPC.
    mcp.run(transport="stdio")
