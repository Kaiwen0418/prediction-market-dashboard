# Prediction Market API

FastAPI + NumPy backend for the Vercel-hosted frontend.

## Local development

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs`.

## Current shared test deployment

The backend runs on `frodo@192.168.1.131`, published at
`https://predict-test.project-echo.xyz` through a named Cloudflare Tunnel.
Run `./deploy/update-local.sh` from the repository root to update the Compose stack.
See [operations](../deploy/README.md). The old Railway deployment is offline and
its GitHub source is disconnected; no Railway data was migrated.

## Legacy Railway deployment (retired)

Historical Railway service setup:

- Root directory: `backend`
- Builder: `Nixpacks`
- Start command: leave empty if `backend/nixpacks.toml` is used, otherwise use `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Python version: `3.11+`

If Railway was previously started with a manual `uvicorn ...` command and no install phase, you'll see `/bin/bash: uvicorn: command not found`. This repo now includes:

- [requirements.txt](/Users/blueberryncherry/Proj/Prediction%20Market%20Intelligence%20Dashboard/backend/requirements.txt)
- [nixpacks.toml](/Users/blueberryncherry/Proj/Prediction%20Market%20Intelligence%20Dashboard/backend/nixpacks.toml)

These force Railway to install the backend dependencies before boot.

Environment variables:

- `APP_ENV=production`
- `FEATURED_MARKET_SLUG=california-governor-election-2026`
- `DATA_API_BASE_URL=https://data-api.polymarket.com`
- `POLYMARKET_WS_URL=wss://ws-subscriptions-clob.polymarket.com/ws/market`
- `POLYMARKET_MARKET_CACHE_TTL_SECONDS=300`
- `POLYMARKET_ORDERBOOK_CACHE_TTL_SECONDS=2`
- `POLYMARKET_TRADES_CACHE_TTL_SECONDS=3`
- `POLYMARKET_HISTORY_CACHE_TTL_SECONDS=300`
- `POLYMARKET_REALTIME_STALE_IF_ERROR_SECONDS=15`
- `POLYMARKET_MARKET_STALE_IF_ERROR_SECONDS=3600`
- `KALSHI_BASE_URL=https://external-api.kalshi.com/trade-api/v2`
- `KALSHI_EVENT_CACHE_TTL_SECONDS=15`
- `KALSHI_ANALYTICS_CACHE_TTL_SECONDS=10`
- `KALSHI_HISTORY_CACHE_TTL_SECONDS=300`
- `KALSHI_STALE_IF_ERROR_SECONDS=300`
- `MARKET_CATALOG_SYNC_INTERVAL_SECONDS=300`
- `MARKET_CATALOG_STALE_IF_ERROR_SECONDS=3600`
- `MARKET_CATALOG_PAGE_SIZE=100`
- `MARKET_CATALOG_MAX_PAGES=20`
- `MONITORING_ENABLED=true`
- `MONITORING_HOT_MARKETS_PER_VENUE=20`
- `MONITORING_WARM_MARKETS_PER_VENUE=120`
- `MONITORING_POLYMARKET_HOT_STREAMS=3`
- `MONITORING_HOT_REFRESH_SECONDS=15`
- `MONITORING_WARM_REFRESH_SECONDS=60`
- `MONITORING_MAX_REFRESHES_PER_TICK=4`
- `POLYMARKET_REQUEST_RATE_PER_SECOND=8`
- `POLYMARKET_REQUEST_BURST=16`
- `KALSHI_REQUEST_RATE_PER_SECOND=8`
- `KALSHI_REQUEST_BURST=16`
- `LIVE_STREAM_ENABLED=true`
- `LIVE_STREAM_INITIAL_DUMP=true`
- `LIVE_STREAM_MAX_MARKETS=6`
- `LIVE_STREAM_IDLE_TTL_SECONDS=300`
- `LIVE_STREAM_CLEANUP_INTERVAL_SECONDS=60`
- `LIVE_STREAM_METRICS_HISTORY_LIMIT=240`
- `ALLOW_ORIGINS=["https://your-vercel-app.vercel.app"]`

## Current endpoints

- `GET /health`
- `GET /api/polymarket/events`
- `GET /api/polymarket/featured-market`
- `GET /api/polymarket/orderbook`
- `GET /api/polymarket/price-history`
- `GET /api/polymarket/trades`
- `GET /api/polymarket/market-context`
- `GET /api/kalshi/events`
- `GET /api/kalshi/analytics`
- `GET /api/catalog/markets`
- `GET /api/monitoring/status`
- `GET /api/live/status`
- `GET /api/live/market-snapshot`
- `GET /api/live/replay`
- `GET /api/live/stream`

The live-stream registry is bounded and self-cleaning:

- the featured slug is kept warm
- additional slug streams are evicted when the registry exceeds `LIVE_STREAM_MAX_MARKETS`
- idle non-featured streams are removed after `LIVE_STREAM_IDLE_TTL_SECONDS`

REST venue reads use a shared in-process cache with per-key single-flight
coalescing. Concurrent browser requests for the same expired key produce one
upstream request. Use one Railway replica with this cache; move it to Redis
before adding replicas.

The market catalog scans paginated active Polymarket events and cursor-paginated
open Kalshi events. It retains political, election, government, and geopolitical
contracts, refreshes every five minutes, and serves one shared snapshot to all
frontend clients. Static frontend slugs and tickers are fallback identifiers and
geographic overrides, not the primary discovery path.

The monitoring scheduler ranks each venue independently by 24-hour volume and
liquidity. The top 20 markets are hot, the next 120 are warm, and the remaining
catalog entries are discovery-only. Hot markets refresh every 15 seconds, warm
markets every 60 seconds, and catalog-only markets do not generate detail
requests. Refreshes are staggered, capped per tick, and pass through shared
per-venue token buckets. Three hot Polymarket markets are proactively streamed,
leaving at least two default stream slots available for user-selected contracts.

Live status metadata now includes:

- `sampleCount`
- `lastSampledAt`
- `lastErrorAt`
- `lastDisconnectReason`

The stream manager also emits structured JSON log lines for registration, connection, progress, eviction, cleanup, and reconnect errors.
- `GET /api/research/states/{state}/summary`
- `GET /api/research/states/overview`
- `POST /api/analytics/lead-lag`
- `POST /api/analytics/correlation`
- `POST /api/analytics/volatility`
- `POST /api/analytics/summary`
- `POST /api/analytics/event-window`

## Tests

```bash
PYTHONPATH=backend python -m unittest discover -s tests
```
