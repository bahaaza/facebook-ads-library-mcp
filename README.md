# Adwatch · Facebook Ad Library MCP

A self-hosted competitor watchlist for a 3D printing business: scheduled public Ad Library scans, a searchable ad gallery, and alerts when previously unseen ad IDs appear. The original two MCP tools remain available.

Forked from [RamsesAguirre777/facebook-ads-library-mcp](https://github.com/RamsesAguirre777/facebook-ads-library-mcp). MIT licensed; see [LICENSE](LICENSE).

## What you can do

- Add competitors using their numeric Facebook Page ID or Ad Library **See all ads** link.
- Monitor each Page in a specific country or all countries, every 1–168 hours.
- Build a quiet first baseline, then receive alerts for newly observed ad IDs.
- Browse collected copy, creative thumbnails, public creative variants, launch dates, and destination links.
- Search copy (including Arabic and Hebrew), filter by competitor, save examples, write notes, group similar copy, and export CSV.
- Inspect every scan, its coverage warning, and the rendered text used as evidence.
- Read alerts in the dashboard; optionally deliver them through email and/or Telegram.
- Pause monitoring without losing history. Failed scans preserve all collected ads.

## Install with Docker

Requires Docker Engine + Compose (Docker Desktop works on macOS/Windows). Linux containers on amd64 or arm64. No host Python, Node, Facebook account, or Meta API token is needed.

```sh
git clone https://github.com/bahaaza/facebook-ads-library-mcp.git
cd facebook-ads-library-mcp
# Until the feature PR is merged:
git switch feat/competitor-monitor
./scripts/setup.sh
```

Open **http://localhost:18473**. Sign in with `ADMIN_USERNAME` and `ADMIN_PASSWORD` from the generated `.env` file. Setup generates two independent random passwords and leaves an existing `.env` intact. Never commit that file.

On Windows, run the script in WSL or create `.env` from `.env.example`, replace both passwords (use hexadecimal characters for the database password), then run:

```sh
docker compose up --build -d --wait
```

The dashboard, API, worker, Chromium, and PostgreSQL install together. PostgreSQL uses a persistent named volume. Containers restart automatically when Docker starts; scans require the host to remain awake. A laptop that sleeps cannot monitor continuously. A small always-on server is a useful eventual home.

The default port binds to **127.0.0.1**, with a sign-in form and an eight-hour HttpOnly session cookie (API clients can also use HTTP Basic). For remote use, put it behind an HTTPS reverse proxy or a private tunnel; set `PUBLIC_URL` to the actual HTTPS address. Use HTTPS for remote access to protect login credentials and session cookies.

```sh
docker compose ps                     # API, DB, and worker should be healthy
docker compose logs --tail=100 worker  # Scan outcomes
docker compose down                   # Stop; retain history
docker compose up -d --wait            # Resume
```

Changing `PORT` also requires changing `PUBLIC_URL`. If port 18473 is already used, set both in `.env` before starting. Do not use `down -v` unless you intend to delete the database volume.

## Build your first watchlist

1. Open [Meta Ad Library](https://www.facebook.com/ads/library/).
2. Find a competitor and choose **See all ads** for its Page.
3. Copy the link containing `view_all_page_id=…` into **Add competitor**.
4. Give it a name, choose `ALL` or a country code, and start with a 12-hour interval.
5. The first readable scan establishes a baseline. Later previously unseen IDs generate one alert per scan, even after restarts.

A Facebook Page handle (`facebook.com/yourcompetitor`) is not a numeric Page ID. Broad keyword searches remain available through MCP, but monitoring uses exact Page IDs to avoid attributing unrelated advertisers to your competitors. Different countries can be separate watchlist entries.

For your printing business, start with 5–10 direct competitors and save examples by offer: personalized gifts, business merchandise, event favors, signage, and seasonal products. Use notes to record the offer, price explicitly shown, turnaround, and CTA. Compare offers and presentation before deciding what to test in your own marketing. The tool does not infer ad budgets or performance.

## Alerts

The dashboard inbox works immediately. External delivery is optional and requires your own notification provider credentials, **not Facebook credentials**.

For email, set these values in `.env`:

```dotenv
SMTP_HOST=smtp.your-provider.example
SMTP_PORT=587
SMTP_USERNAME=your-username
SMTP_PASSWORD=your-app-password
SMTP_FROM=adwatch@your-domain.example
SMTP_TO=you@your-domain.example
SMTP_TLS=starttls
```

For implicit TLS use `SMTP_TLS=ssl` and your provider's TLS port, usually 465. Both modes verify certificates. Multiple email recipients may be comma separated.

After restarting services, open **Settings & delivery** and click **Send test email**. It sends one message to `SMTP_TO` and shows whether your mail server accepted it. Check your inbox and spam folder to confirm receipt.

For Telegram, create a bot with BotFather, start a conversation with it, then set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Set both values together. The token is never returned to the browser or logged.

After editing configuration:

```sh
docker compose up -d --force-recreate api worker
```

New alerts enter a database-backed delivery outbox in the same transaction as their ad records. Delivery retries after 2, 4, 8, and 16 minutes; after five attempts it is marked failed. Fix configuration and use **Retry** in the inbox. Events generated before a channel was configured remain in the dashboard; they are not retroactively emailed.

New ads are bundled into one event per competitor scan. The first consecutive scan failure creates an interruption alert; repeat failures stay quiet until recovery. Recovery creates its own event. Delivery is **at least once**: a crash after a provider accepts a message but before the DB commit can duplicate that external message. Every message includes an event ID. Database ad events are deduplicated.

## Architecture and reliability

- **React 19 + TypeScript + Vite**: responsive dashboard, served by FastAPI from the production build.
- **FastAPI + SQLAlchemy + PostgreSQL 17**: authenticated API, persistent watchlist/history/alerts, and an outbox.
- **Playwright Chromium**: anonymous public-page rendering. It reads structured data embedded in the page and browser responses, with rendered text as a fallback. No token, login automation, or borrowed browser cookies.
- **Dedicated Python worker**: durable scheduling and serial browser scans. PostgreSQL advisory leadership prevents duplicate workers; unique active-scan indexes protect racing producers. Queued work survives API restarts.
- **Docker Compose**: one reusable application image, separate API and worker containers, and a database volume. Dependencies are locked in `uv.lock` and `web/package-lock.json`.

The worker waits at least 30 seconds between browser scans by default, adds schedule jitter, and backs off unreadable Pages for 2, 4, 8, 16, then up to 24 hours. A full render has a 180-second timeout and bounded scrolling. A crashed running scan is recovered after its 10-minute lease expires. Paused queued scans are cancelled; an already running scan may finish.

The initial schema is created automatically on startup. This is the first schema version; future schema changes need an explicit migration rather than deleting the database.

### What the data means

- **Newly observed** is different from **newly launched**. An old ad outside the original baseline's scroll coverage can appear as newly observed later. The Meta launch date is shown separately.
- A scroll limit or a first-viewport-only scan is marked as **partial coverage**. Even a stable page does not guarantee exhaustive results; Facebook's public rendering can change.
- A missing card does not prove an ad has stopped. We retain history and last-seen timestamps. There are no inferred “stopped” alerts.
- HTTP 403 can accompany readable ad cards. Success is based on actual parsed cards; an empty response, login prompt, or block is a failed read. A confirmed empty scan requires an explicit empty-results message.
- Similar-copy grouping operates within the current gallery page, using copy/headline/CTA/destination, and does not prove identical media or campaign identity.
- Thumbnails are remote public CDN links and can expire. Copy and extracted metadata persist; original Ad Library links remain available. Media is not downloaded or archived.
- Some fields may be unavailable, especially video media and dynamic ad variants. The details dialog shows up to 20 public variants when available. Open the original ad for the full presentation.
- Exact-Page scans verify numeric advertiser Page IDs from the public data. Unverified or other-Page records are excluded and mark coverage as partial. If visible cards cannot be attributed to the requested Page, the scan fails rather than mislabelling them.
- Longevity, ad counts, and repeated creatives do not establish spend, sales, or profitability.

## Backups

```sh
./scripts/backup.sh
# Restore a selected backup into this app's database (overwrites matching tables):
docker compose stop api worker
docker compose exec -T db psql -U adwatch -d adwatch < work/backups/YOUR-BACKUP.sql
docker compose up -d --wait
```

Backups contain your notes and watchlist; protect them and copy them to another device. Keep `.env` separately. Upgrade code with `git pull`, then rebuild with `docker compose up --build -d --wait`. Back up before upgrading.

## MCP usage

The original tool names and parameters remain: `search_ad_library` and `scrape_ad_library_url`. Tools are async to avoid nested `asyncio.run` errors, and stdio contains only MCP protocol traffic.

After building the Docker image, register the following command in your MCP client:

```sh
docker run --rm -i adwatch:local python facebook_ads_mcp_complete.py
```

```json
{
  "mcpServers": {
    "facebook-ads": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "adwatch:local", "python", "facebook_ads_mcp_complete.py"]
    }
  }
}
```

Example: `Search the Ad Library for personalized gifts in IL.` MCP calls do not write to the dashboard watchlist/history; scheduled monitoring is managed through the UI.

## Development and tests

```sh
uv sync --frozen --dev
uv run python -m playwright install chromium
cd web && npm ci && npm run build && cd ..
# Set a strong ADMIN_PASSWORD before starting locally.
# Local development defaults to SQLite in work/; run exactly one local worker.
mkdir -p work
uv run uvicorn adwatch.api:app --host 127.0.0.1 --port 18473
# In another terminal:
uv run python -m adwatch.worker
```

Production Compose always uses PostgreSQL. SQLite is for tests and single-worker local development; it does not provide the PostgreSQL leadership guarantee.

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
RUN_BROWSER_TESTS=1 uv run pytest tests/test_browser.py -q
# Dedicated disposable database; name must end in _test. These tests drop its schema.
TEST_POSTGRES_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/adwatch_test uv run pytest tests/test_postgres.py -q
```

The browser tests launch real Chromium against controlled HTML and the production UI. They do not scrape Facebook. Live Facebook scans should be occasional manual smoke checks, not part of CI. CI runs parser/monitor/API/outbox/MCP/PostgreSQL/UI checks and builds the Docker image.

## Fixes relative to upstream

- Replaced substring URL checks with parsed, exact Facebook-host/path validation.
- Fixed first-card and bold-ID parsing, single-pass landing URL decoding, multiline/case-insensitive CTAs, advertiser-avatar confusion, and neighboring-card status leakage.
- Collects cards before each scroll step to handle virtualized lists, enriches them from public structured data, and verifies Page identity before monitoring attribution.
- Separates unreadable results from confirmed empty scans; bounds timeout and scan controls.
- Preserves full parsed copy, exposes coverage warnings, and removes non-protocol stdout from MCP.
- Uses one Playwright renderer for both MCP and the monitor instead of the larger Crawl4AI dependency stack.
