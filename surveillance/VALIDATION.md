# Local validation — 2026-10-28

- Python 3.12, dedicated temporary PostgreSQL 17 cluster, temporary raw archive.
- 16 surveillance tests passed, including actual PostgreSQL integration tests.
- Existing backend suite: 54 tests passed.
- `compileall` passed for `backend/app` and `surveillance`; `git diff --check` passed.
- Public endpoint probes: Polymarket keyset catalog and `/v2/trades`, Kalshi
  market catalog and market trades all returned HTTP 200 with expected envelopes.
- One bounded live trade page per venue was passed through the real worker's
  normalization, PostgreSQL persistence and atomic Parquet archive paths:
  Polymarket 167 rows, Kalshi 1,000 rows. Both archived responses passed SHA-256
  verification. These counts are smoke-test observations, not coverage metrics.
- API smoke runs in-process through ASGI with real PostgreSQL: authentication,
  health, case/report, replay, raw evidence, review versions, manual information
  and later case attachments were verified.

No production database, remote SSH connection, deployment, continuous collection,
frontend/browser change, automatic trade, or seven-day calibration was performed.
Temporary live/test schemas and raw archives were removed after verification.
The local PostgreSQL cluster was stopped and disposable test runtime removed before
handoff. Follow CI for validation of the published commit.
