# Examples

## Competitor watchlist

In the UI, add a competitor's numeric Page ID or its `https://www.facebook.com/ads/library/?view_all_page_id=…` link. Choose a country or `ALL`, then a 12-hour interval. The initial successful scan establishes a quiet baseline.

For a 3D printing business, save ads for event favors, personalized gifts, promotional merchandise, and seasonal products. Record the actual advertised offer, price, turnaround, and CTA in your notes. Inspect the original ad and landing page before drawing conclusions.

## MCP discovery

```python
search_ad_library(query="personalized gifts", country="IL", scroll_rounds=8)
search_ad_library(query="3d printing", country="ALL", scroll_rounds=8)
# Replace with an actual numeric Facebook Page ID:
search_ad_library(advertiser_page_id="YOUR_NUMERIC_PAGE_ID", country="ALL")
scrape_ad_library_url(url="YOUR_AD_LIBRARY_URL", scroll_rounds=8)
```

A Page handle is not a Page ID. Keyword discovery can return unrelated advertisers. Monitoring intentionally uses exact Page IDs; it does not silently fall back to broad searches.

Check `success`, `outcome`, and `partial` before interpreting results. Empty/unreadable markup does not establish that a competitor has no ads. Launch dates and creative counts do not demonstrate performance or spend. See the [data interpretation notes](../README.md#what-the-data-means).
