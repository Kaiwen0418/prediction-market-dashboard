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

## Public endpoint and cutover

Approved hostname: **`predict-test.projext-echo.xyz`**.
Create a separate named Cloudflare Tunnel pointing to `http://127.0.0.1:18000`.
Add the proxied CNAME for `predict-test` to that tunnel's returned `<id>.cfargotunnel.com`
target in the `projext-echo.xyz` zone. Run its connector as a persistent service on
the development machine. The existing AgentBench tunnel need not be migrated.

The included `pmi-api-tunnel.service` is only the temporary Quick Tunnel used for
REST verification. It auto-starts as a user service but creates a new hostname on
restart and does not support SSE; do not use it as the final frontend backend.
Replace it with the named tunnel when its credentials are available.

Cutover uses the following concrete settings:

```text
NEXT_PUBLIC_API_BASE_URL=https://predict-test.projext-echo.xyz
```

Update this variable for the existing Vercel project's Production and Preview
environments, then redeploy the existing frontend without merging PR #15. Next.js
inlines `NEXT_PUBLIC_` values at build time; changing the variable alone is insufficient.

Verify fixed-host `/health`, `/api/polymarket/market-context`,
`/api/research/states/Arizona/summary?party=Republican`, and
`/api/live/stream?slug=california-governor-election-2026` (SSE receives `event: snapshot`).
Then verify normal browser selection and the new API origin in network traffic.
Stop/remove the Railway test deployment once the frontend cutover succeeds.
Remove/stop the temporary Quick Tunnel after the named tunnel works.

At this handoff, the local containers and temporary REST endpoint are live. Named
tunnel/DNS creation, Vercel variable/redeployment and Railway shutdown remain to be
performed after the newly connected app interfaces load into a new chat turn.
This is a tool availability issue, not a request for new authorization.

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
