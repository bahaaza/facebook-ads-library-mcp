# Rendering implementation

Upstream used Crawl4AI. This fork uses Playwright directly to share a bounded renderer between MCP tools and the scheduled monitor.

See [adwatch/scraper.py](../adwatch/scraper.py), [adwatch/parser.py](../adwatch/parser.py), and the [reliability notes](../README.md#architecture-and-reliability).

The browser opens anonymous public Ad Library pages, waits for rendering, handles an optional public cookie consent prompt, and collects Markdown snapshots before and during scrolling. Scripts/styles are removed. Parsed ad IDs are deduplicated and enriched across snapshots. Structured records embedded in the public page and its browser responses supply numeric Page identity, platform labels, and creative variants. Monitoring excludes records that cannot be verified against the requested Page ID; keyword MCP discovery retains a Markdown fallback. The renderer checks for cards or an explicit empty-results message, rather than relying on HTTP status alone.

No Facebook credentials, API access tokens, or browser-session cookies are supplied. Rendering can still be blocked or incomplete. Failures and coverage warnings are visible in the dashboard.
