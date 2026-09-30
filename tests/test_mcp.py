import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_protocol_and_tools():
    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(Path(__file__).parent.parent / "facebook_ads_mcp_complete.py")],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == {
                    "search_ad_library",
                    "scrape_ad_library_url",
                }
                result = await session.call_tool(
                    "scrape_ad_library_url", {"url": "https://evil.test/facebook.com/ads/library/"}
                )
                assert not result.isError
                assert result.structuredContent["success"] is False

    asyncio.run(check())
