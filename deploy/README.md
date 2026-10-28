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
