# AGENT Workflow

## Branch Model

- `dev`
  - Integration branch.
  - All feature branches should merge here first.
  - Preview deployment should track this branch.
- `main`
  - Production branch.
  - Only promote code from `dev` after CI and smoke checks pass.
  - Production deployment should track this branch.

Recommended GitHub protection rules:

- Protect `dev` and `main`.
- Require pull requests before merge.
- Require the `CI / backend` and `CI / frontend` jobs to pass.
- Disable direct pushes to `main`.

## CI/CD Layout

- `.github/workflows/ci.yml`
  - Runs on pushes and pull requests to `dev` and `main`.
  - Splits backend and frontend validation into separate jobs.
- `.github/workflows/deploy-preview.yml`
  - Deploys Vercel preview from `dev`.
- `.github/workflows/deploy-production.yml`
  - Deploys Vercel production from `main`.

Required GitHub secrets for Vercel deploy workflows:

- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`

The backend test deployment runs on `frodo@192.168.1.131` using `deploy/local.compose.yml`;
update it with `deploy/update-local.sh`. The public API is `https://predict-test.project-echo.xyz`.
Railway is offline and its GitHub source is disconnected. Frontend hosting stays on Vercel.
For the current surveillance/migration task, keep PR #15 draft and unmerged until the user requests integration.

## Local Environment

Frontend:

- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_APP_URL`

Backend:

- `APP_ENV`
- `ALLOW_ORIGINS`
- `FEATURED_MARKET_SLUG`

Use the checked-in `.env.example` as the frontend baseline. Keep local secrets in `.env.local` and `backend/.env`.

## Agent Delivery Flow

1. Branch from `dev` unless the task is a production hotfix.
2. Implement the change.
3. Run the minimum local checks that match the touched surface.
4. Prefer a single intentional commit for the current batch of work unless the task explicitly needs a split history.
5. Push the branch immediately after the commit.
6. Use `gh` CLI to inspect the GitHub Actions state for the pushed commit before reporting completion.
7. Open or update a PR into `dev`.
8. After merge to `dev`, verify preview deployment and browser smoke checks.
9. Promote `dev` to `main` with a dedicated PR.
10. After merge to `main`, verify production deployment and browser smoke checks.

Required post-commit GitHub Actions checks:

- `gh run list --limit 5`
- `gh run view <run-id> --log-failed` when any job is not green
- Do not claim completion until the relevant `CI` and deploy workflows are either:
  - passing, or
  - explicitly documented as still running / blocked

Required post-commit browser checks:

- Open the deployed page or local preview in the browser.
- Confirm the touched route renders without a client-side exception.
- Confirm the primary interaction path for the touched surface still works.
- If a client-side exception appears, fix it before closing the task.

## Mandatory Validation

Backend:

- `python3 -m compileall backend/app`
- `PYTHONPATH=backend python -m unittest discover -s backend/tests`

Frontend:

- `pnpm typecheck`
- `pnpm build`

If local Python dependencies are missing, install `backend/requirements.txt` into a Python 3.11 environment before claiming backend validation is complete.

## Integration Smoke Checklist

Run these after merging into `dev` and again after promoting to `main`.

### Backend health

- `GET /health` returns `status=ok`.
- `GET /api/polymarket/market-context` returns:
  - `featuredMarket`
  - `orderbookSummary`
  - `priceHistoryMeta`
  - `timelineEvents`
- `GET /api/polymarket/orderbook-summary?tokenId=...` returns non-empty summary fields.
- `GET /api/research/states/Arizona/summary?party=Republican` returns:
  - `coverage`
  - `narrative`
  - `researchHighlights`

### Frontend smoke

- `/`
  - Hero renders.
  - Theme switch works across `light -> dark -> light`.
- `/market`
  - Market loads without fallback-only error.
  - Clicking a spotlight state changes the live market context.
  - Right rail updates title, source dots, and orderbook summary metrics.
  - Price history chart renders annotations.
- `/history`
  - State toggle works.
  - Party toggle works.
  - Coverage line renders.
  - Rolling correlation chart renders when aligned data exists.
  - Additional analytical overlays and parameter charts render without client-side exceptions.

### Data-source diagnostics

- `featured-market`
- `market-context`
- `orderbook`
- `orderbook-summary`
- `price-history`
- `history-backend:{state}:{party}`

At least confirm whether each is `live`, `fallback`, or `failed`. Do not ship a change without noting any remaining fallback paths.

## Notes For Future Agents

- Do not commit `.claude/worktrees`.
- Prefer backend-owned aggregation routes over adding new frontend orchestration.
- When analytics semantics change, update both:
  - backend implementation/tests
  - frontend fallback implementation
