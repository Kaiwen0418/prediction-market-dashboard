# Local test deployment

Target: `frodo@192.168.1.131`, source at `/home/frodo/prediction-market-dashboard`.
The existing Vercel frontend stays on Vercel; the former Railway backend runs here.
No database export/import, backups, replication or blue/green infrastructure are required.

From the repository root:

```sh
./deploy/update-local.sh
```

This copies the backend, investigation module and bundled `public/data`, creates
`deploy/.env` on the server if absent, builds one shared Python image, then starts
four containers. It does not merge a branch or modify external DNS/Vercel settings.
Existing server credentials are not overwritten and are never printed.

| Service | Endpoint / role | Memory ceiling |
| --- | --- | --- |
| backend | `http://192.168.1.131:18000` | 1 GiB |
| surveillance-api | `http://192.168.1.131:18010`, Bearer token | 512 MiB |
| surveillance-worker | background collection / detection / maintenance | 1 GiB |
| postgres | private Compose network, no host DB port | 768 MiB |

The deployment starts with 20 contracts per venue, not the module's 100 default.
Change `SURVEILLANCE_CONTRACTS` in the server's `deploy/.env`, then run Compose up
again. See the measured capacity report before increasing this budget.

## Operations on the server

```sh
cd ~/prediction-market-dashboard
docker compose --env-file deploy/.env -f deploy/local.compose.yml ps
docker compose --env-file deploy/.env -f deploy/local.compose.yml logs --tail 50 surveillance-worker
docker compose --env-file deploy/.env -f deploy/local.compose.yml exec -T surveillance-worker python -m surveillance.cli coverage
```

Credentials live only in the server's mode-0600 `deploy/.env`. To read API health
without exposing the token in command arguments or output:

```sh
docker compose --env-file deploy/.env -f deploy/local.compose.yml exec -T surveillance-api python -c \
'import os,httpx; r=httpx.get("http://127.0.0.1:8010/health",headers={"Authorization":"Bearer "+os.environ["SURVEILLANCE_API_TOKEN"]}); print(r.status_code,r.json())'
```

For a deliberate fresh test reset, `docker compose ... down -v` removes this
project's database and evidence volumes. There is no migration data to preserve.
Do not use global Docker pruning or stop unrelated Compose projects.

## Public endpoint and completed cutover

Public API: **`https://predict-test.project-echo.xyz`**.
A proxied CNAME in the `project-echo.xyz` zone points to named Tunnel
`63fae5cf-2ed7-43f3-9bb3-ee427d57aeb0` (`prediction-market-test`).
The connector runs as `systemctl --user status pmi-api-tunnel` under frodo,
with user lingering enabled. Its origin is `http://127.0.0.1:18000`.
The earlier temporary Quick Tunnel has been replaced and is no longer running.
The legacy Quick Tunnel unit in this folder is an unused example.

To configure the named tunnel on this machine after normal Cloudflare CLI login:

```sh
bash deploy/install-named-tunnel.sh
```

The installer checks that the hostname belongs to the authenticated zone **before
any mutation**. Cloudflared otherwise silently appends the selected zone to an
out-of-zone hostname. It creates/reuses the named tunnel, validates ingress,
creates the DNS record and installs `pmi-api-named-tunnel.service` as the user's
`pmi-api-tunnel.service`. Generated `deploy/tunnel.yml` and connector credentials
remain server-local and are excluded from source sync/version control.

Production and Preview now share the following Vercel variable:

```text
NEXT_PUBLIC_API_BASE_URL=https://predict-test.project-echo.xyz
```

Production deployment `dpl_2BmnBiHkMQSEeFZm4Hy1Kq8QzWL8` rebuilt the existing
production commit `77f887f2a413c2397cd5f98200c20fad27940862` on main.
The draft branch was not deployed as frontend production and PR #15 was not merged.
The production alias remains `https://prediction-market-intelligence-dash.vercel.app`.

Verify streaming with the descriptive probe User-Agent (the zone rejects the
stock Python urllib User-Agent):

```sh
python3 deploy/check-sse.py --base https://predict-test.project-echo.xyz
```

Fixed-host health, market context, catalog, research, readiness and SSE passed.
Native browser fetch/EventSource, market selection and CORS passed. The browser
made no requests to Railway. Screenshots are under `tmp/surveillance-migration/`.

The former Railway service in project `determined-patience` is offline, with no
active deployments or mounted volumes. Its GitHub source is disconnected, so
future repository pushes do not restart it. Its previous health URL returns 404.
No dataset export/import, backups, or dual writes were performed.
See [final verification](../docs/local-migration-2026-10-28.md).

## Reproduce the measurements

```sh
# The service environment provides the local database URL.
docker compose --env-file deploy/.env -f deploy/local.compose.yml run --rm --no-deps surveillance-worker \
  python -m surveillance.benchmark --contracts 200 --trades-per-contract 1000 --replays 20

docker compose --env-file deploy/.env -f deploy/local.compose.yml run --rm --no-deps surveillance-worker \
  python -m surveillance.catalog_benchmark --mode stream --contracts 100000
```

Each benchmark creates and removes only its random schema and scratch archive.
The HTTP benchmark script is `deploy/benchmark-http.py`; execute with httpx installed
against `/health` and `/api/polymarket/market-context`. Measurements are warm and short.

### Automatic capacity overwrite

The disposable surveillance dataset has a **20 GiB PostgreSQL admission budget**
and a **5 GiB raw archive budget**, configurable with
`SURVEILLANCE_DATABASE_MAX_BYTES` / `SURVEILLANCE_RAW_MAX_BYTES` in `deploy/.env`.
The worker checks at startup and at most every 60 seconds between jobs/pages.
At 80% of either budget it pauses collection and evicts the oldest response
receipts in batches of 10,000, removing dependent catalog/rule/trade/information
records and entire cases whose evidence expires. Capacity eviction overrides
manual evidence and case pins; export anything worth keeping separately.
Discovery cursors survive, so discovery advances rather than restarting.

Each batch also removes orphan raw files and runs `VACUUM FULL` on the affected
surveillance tables to return file space to the OS. The target is below 60% of
**both** budgets; at most eight batches run per check. If still above 80%,
collection stays paused and retries after 60 seconds. Investigation write APIs
return 503 with Retry-After while above the watermark. `/capacity` (bearer auth)
reports usage, budgets and the last eviction. `/coverage` records an eviction gap;
retained catalogs are a rolling subset, not a complete historical inventory.

An exclusive advisory lock serializes collection/API transactions with deletion,
file removal and compaction. Investigation API calls may wait during compaction;
the separate dashboard backend continues normally. Use one collection worker.
These are application admission budgets, **not filesystem hard quotas**: an
in-flight page/API call, PostgreSQL WAL, Docker images/logs and VACUUM scratch
space are additional. Keep at least 20 GiB free on the host for maintenance.

### Lightweight discovery (v2)

Automatic discovery now walks Polymarket `closed=false` and Kalshi
`status=open&mve_filter=exclude`, with no topic/scope restriction. Closed history
and MVE combinations are not automatically expanded. Catalog jobs use new
`active:v2` identities so old opaque cursors cannot cross query scopes; legacy
catalog jobs are disabled at startup. Completed walks repeat every six hours. At completion, up to 50,000 index rows
not observed since that walk began expire, preserving case/manual references.
Disappearance is not labelled settlement. Selection requires observations within
two catalog intervals; unused rule snapshots expire through ordinary retention.

The catalog omits rule prose and token IDs; all outcomes and lifecycle flags stay
in the index. Only selected contracts receive a five-minute detail job, which
stores versioned rules once. `settled`, `source_status`, `settlement_result`,
`tradable` and `is_combo` preserve upstream state. Deep selection excludes pending
resolution, paused/initialized/settled/combination contracts and schedule end times
more than six hours old. This last test is a budget policy, not a declaration of
settlement; metadata with incorrect end times can be missed. Twenty percent of
selection remains hourly rotating exploration.

Settings in `deploy/.env`: `SURVEILLANCE_CATALOG_SECONDS=21600`,
`SURVEILLANCE_END_GRACE_HOURS=6`, and
`SURVEILLANCE_AUTOMATIC_MIN_CASH_USD=1000`. The automatic dossier cash floor requires
at least five fills, or a single-window notional of at least $10,000. Buy and sell
signals remain eligible. Raw anomaly scores/manual replay remain available;
this is a cost floor, not an insider classifier or calibrated probability.

Closed-market backfill is explicit (numeric Polymarket market ID / Kalshi ticker):

```sh
python -m surveillance.cli backfill --venue polymarket --market 916440 --since 2025-12-26T00:00:00Z
```

The single worker resolves details then follows the trade cursor to the requested
lower boundary and disables completed manual jobs. The scheduler does not disable
unfinished manual jobs. Historical records keep their actual collection timestamps;
strict as-of replay cannot pretend they were received in 2025. Kalshi contracts
already moved to its historical archive may require a future archive adapter;
a 404 is an explicit failed job, not a completed backfill. Backfill shares the
same storage/capacity budgets and is not a permanent exemption from eviction.

For this disposable test dataset the first optimized deployment resets the old
surveillance tables and archive, freeing file space without rewriting millions of
old documents. Stop the worker and investigation API, build the image, then run:

```sh
docker compose --env-file deploy/.env -f deploy/local.compose.yml run --rm --no-deps surveillance-api python -m surveillance.cli reset-test-data --confirm-test-data
docker compose --env-file deploy/.env -f deploy/local.compose.yml up -d --no-build
```

This truncates only this module's known tables and deletes its configured raw
folder, not the database or unrelated tables. Schema and credentials survive.
Normal `update-local.sh` does not reset data. PostgreSQL and raw budgets remain
20 GiB / 5 GiB with the existing 80%→60% eviction policy. Detailed rules for old
selected contracts still expire by capacity/retention policy; catalogs are not a
complete historical inventory.


Surveillance schema 3 uses 100 deep contracts per venue and independent public global
trade walks. Set `SURVEILLANCE_CONTRACTS=100` in the existing `deploy/.env` to override
an older 20-contract setting; the update script preserves private credentials and
existing operator overrides. Wide capture and deep fallback have separate queue
cadences (15s after completed global walks, 900s deep fallback, 1800s rules), with
explicit cursor backlog and source lag in coverage. Update now stops the sole worker
and releases abandoned leases before bringing it back; checkpoints and data remain.
