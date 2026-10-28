# Local backend migration verification — 2026-10-28

The Railway-to-development-machine cutover is complete. PR #15 remains draft and
unmerged; the surveillance frontend remains independent of the dashboard.

| Resource | Final state |
| --- | --- |
| Vercel production frontend | https://prediction-market-intelligence-dash.vercel.app |
| API | https://predict-test.project-echo.xyz |
| Backend origin | `frodo@192.168.1.131`, `http://127.0.0.1:18000` |
| Investigation API | `http://192.168.1.131:18010`, Bearer token required |
| Deployment source | existing main commit `77f887f2a413c2397cd5f98200c20fad27940862` |
| New Vercel deployment | `dpl_2BmnBiHkMQSEeFZm4Hy1Kq8QzWL8`, production, READY |
| Named Tunnel | `prediction-market-test`, `63fae5cf-2ed7-43f3-9bb3-ee427d57aeb0` |
| DNS | proxied CNAME `predict-test.project-echo.xyz` → `63fae5cf-2ed7-43f3-9bb3-ee427d57aeb0.cfargotunnel.com` |
| Tunnel service | frodo user service `pmi-api-tunnel`, enabled, lingering enabled |
| Railway project | `determined-patience`, `25fefec9-4bb3-451a-8030-6485ff95c57e` |
| Railway service | `f0150217-4298-4f2c-9107-8c68fd57dd0a`, Offline, no active deployments |
| Railway source | disconnected (repo/image null); repository pushes cannot redeploy it |

## Evidence

- Fixed-host `/health`, `/api/catalog/markets`, `/api/polymarket/market-context`,
  `/api/research/states/Arizona/summary?party=Republican`, and `/api/live/readiness`
  returned 200. Readiness was true; CORS allowed the Vercel frontend.
- Public SSE returned `text/event-stream`, with three connected snapshots at
  0.127s, 1.129s and 2.133s, all carrying the requested market's orderbook summary.
- Native browser EventSource independently received three connected snapshots in
  2.04s. No fetch or EventSource overrides were used for final production validation.
- The real production page selected the California wealth-tax market, updated its
  heading, and made requests to the fixed host. The observed resource list contained
  64 new-backend requests and zero Railway requests; runtime exceptions were zero.
- After Railway shutdown, the new backend still returned 200 from the browser,
  while the former Railway health URL returned 404. Railway API confirmed Offline,
  empty activeDeployments, no pending work, no volume and no shared variables.
- A deployment-specific Vercel error/fatal log query over the recent 15-minute
  window returned no matching logs. This is a short verification window, not a
  long-term reliability or detection-calibration claim.
- The authenticated Cloudflare API confirmed the intended proxied CNAME and zero
  records for the accidentally appended hostname. The installer now rejects an
  out-of-zone hostname before any mutation; this rejection was exercised directly.

Screenshots are retained locally at:

- `tmp/surveillance-migration/production-fixed-domain.png`
- `tmp/surveillance-migration/production-after-railway-stop.png`

No Railway dataset was copied or retained for migration. The four Compose services
and the named tunnel intentionally remain running on the development machine.
The deployment uses 20 contracts per platform; storage and sampling limits are
recorded in [the capacity assessment](surveillance-capacity-2026-10-28.md).

## Repeat the checks

```sh
python3 deploy/check-sse.py --base https://predict-test.project-echo.xyz
ssh -i ~/.ssh/agentbench_codex_ed25519 frodo@192.168.1.131 \
  'cd ~/prediction-market-dashboard; docker compose --env-file deploy/.env -f deploy/local.compose.yml ps; systemctl --user is-active pmi-api-tunnel'
```

CLI credentials and Cloudflare connector credentials stay in the normal user/server
credential locations. No token, certificate contents, browser auth state, or
secret-bearing trace is committed to the repository or attached as an artifact.
