# Prediction Market Intelligence Dashboard

Prediction-market research product with a Vercel-hosted Next.js frontend and a FastAPI + NumPy backend on the local development machine. The app combines live Polymarket data, cached research datasets, quantitative analytics, and editorial visualization.

## Product Structure

- `/` Home: hero + embedded live market surface
- `/history` Research: cached polling vs market comparison
- `/market` Redirects to `/`

## Core Capabilities

- Live featured market and orderbook view
- Interactive U.S. state map with market rail
- Annotated Polymarket price-history chart
- Research-grade polling vs market comparison page
- Client-side analytics for lead-lag, correlation, volatility, and liquidity

## Stack

- Frontend: Next.js App Router, TypeScript, Zustand, TanStack Query, ECharts, Tailwind CSS
- Backend: FastAPI, NumPy, httpx
- Visualization: Three.js, react-simple-maps

## Local Development

```bash
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000).

### Optional backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```

Open [http://localhost:8000/docs](http://localhost:8000/docs).

## Deployment Split

### Frontend on Vercel

- Framework preset: `Next.js`
- Install command: `pnpm install --frozen-lockfile`
- Build command: `pnpm build`
- Node version: `24.x`
- Environment variable: `NEXT_PUBLIC_API_BASE_URL=https://predict-test.project-echo.xyz`

### Backend on the development machine

- Host: `frodo@192.168.1.131`
- Deploy: `./deploy/update-local.sh`
- Public API: `https://predict-test.project-echo.xyz`
- Runtime: Docker Compose, Python 3.12, PostgreSQL 17, persistent named Cloudflare Tunnel
- Railway deployment is offline and disconnected from its GitHub source.
- See [operations](deploy/README.md) and [migration verification](docs/local-migration-2026-10-28.md).

The frontend falls back to its local Next.js route handlers if `NEXT_PUBLIC_API_BASE_URL` is not set.

## Public Data Assets

- Polling dataset: [public/data/state-party-support-2024.json](/Users/blueberryncherry/Proj/Prediction%20Market%20Intelligence%20Dashboard/public/data/state-party-support-2024.json)
- Cached Polymarket history: [public/data/polymarket-history-2024.json](/Users/blueberryncherry/Proj/Prediction%20Market%20Dashboard/public/data/polymarket-history-2024.json)

## Validation

```bash
pnpm typecheck
pnpm build
```

```bash
python3 -m compileall backend/app
```

Or provide a local CSV path:

```bash
pnpm generate:state-support -- /tmp/presidential_general_averages_2024-09-12_uncorrected.csv
```

## Notes

- The frontend still supports its original Next route handlers for local or fallback use.
- The FastAPI backend currently owns the live Polymarket proxy layer and NumPy analytics endpoints.
- This split is intended to showcase both frontend systems thinking and backend/data-engineering ability.


### Local test migration and independent surveillance

The unmerged surveillance branch includes a local Docker Compose deployment for
`frodo@192.168.1.131`. See [deployment instructions](deploy/README.md) and the
[measured capacity assessment](docs/surveillance-capacity-2026-10-28.md).
The Vercel frontend now uses the fixed public Tunnel; PR #15 remains draft and unmerged.
