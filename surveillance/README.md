# Market Surveillance — first implementation

Independent Python/asyncio + FastAPI + PostgreSQL + Parquet service. No imports from
`backend/app`, no existing market-scope filters, no frontend changes, and no order
placement or trading credentials. This is the collection and investigation foundation;
it is **not the complete investigation system described in the roadmap**.

## Run locally

Python 3.11+ and PostgreSQL 14+ are required. Run commands from the repository root:

```sh
python3.12 -m venv .venv-surveillance
.venv-surveillance/bin/pip install -r surveillance/requirements.txt
export SURVEILLANCE_DATABASE_URL='postgresql://USER:PASSWORD@127.0.0.1:5432/surveillance'
export SURVEILLANCE_RAW_DIR='/absolute/path/to/surveillance-data'
export SURVEILLANCE_API_TOKEN='a-random-secret'
.venv-surveillance/bin/python -m surveillance.cli init
.venv-surveillance/bin/python -m surveillance.cli worker
```

In another terminal with the same environment:

```sh
.venv-surveillance/bin/uvicorn surveillance.api:create_app --factory --host 127.0.0.1 --port 8010
```

API routes require `Authorization: Bearer <SURVEILLANCE_API_TOKEN>`. Missing server
configuration fails closed. Protect the API with HTTPS before exposing it remotely.
Interactive endpoint definitions are at `/docs`; OpenAPI metadata contains no evidence.

`surveillance/deploy/market-surveillance.service` is an optional Linux systemd worker
unit. Create its user, environment file, virtualenv and writable data directory first.
It has not been installed on the remote machine. Use a separate API process as above.
The process handles SIGINT/SIGTERM through asyncio cancellation; hard termination
recovers after the five-minute database lease expires.

## Implemented

- Independent unfiltered contract catalog: Polymarket keyset walks for **both open
  and closed** markets; Kalshi market pagination. Preserve every returned contract,
  every outcome/token and each changed rule snapshot, including reverted rules.
- Read-only Polymarket **`/v2/trades`** and Kalshi REST collection. Fixed filters on
  every cursor page. Empty v2 pages with a next cursor continue; malformed envelopes,
  repeated cursors, detected cursor cycles and ordering violations are explicit errors.
- PostgreSQL queue with `FOR UPDATE SKIP LOCKED`, expiring leases, fencing tokens,
  atomic normalized rows/checkpoints and exponential retry. A failed page cannot
  advance the cursor. Valid HTTP error responses are archived before raising errors.
- Exact response bytes in immutable, atomic Parquet files with SHA-256, source,
  query, status and receipt timestamp. `verify` reopens files and checks hashes.
  Identical response bytes share a content-addressed blob; each HTTP receipt retains its own database provenance. Crash-orphaned Parquet files
  may remain if the database index commit failed; they are not silently deleted.
- Default budget: 100 selected contracts per venue, with 20% hourly rotating
  exploration. Rules/category keywords and proximity provide an initial ranking;
  no category is excluded from discovery. Paused jobs preserve cursors. Active
  candidates cause an immediate collection request within the selected budget.
- Versioned 1-minute / 5-minute / 1-hour volume, direction and price-change
  detectors. Per-market median/MAD over 12 preceding windows. At least six nonempty
  baseline windows are required to use the volume-spike component.
- Persisted candidate dossiers with trade/raw references, frozen rule version,
  replay input IDs, score components, wallet observations where attributable,
  alternative explanations and open questions. API/CLI reports and versioned reviews.
- Manual public-information evidence intake and attachment to an existing case.
  Later investigation evidence creates a new case version **without changing the
  original detection score or as-of public timeline**.

## Semantics and limits

**Discovery is not complete until its walks finish.** Catalog page budgets yield
and resume. `coverage` exposes pending cursors, errors, receipt times, selected
budgets and completed walks; it never declares whole-platform coverage based on an
unknown denominator. Kalshi historical archive discovery is not yet integrated.
The catalog preserves all records actually returned by these endpoints.

Trade bootstrap covers the last 13 hours, not all history. A newest-first walk stops
only after crossing its lower bound, including every row at the boundary second.
Polymarket condition feeds ignore time filters: the worker walks the cursor and
applies the boundary locally. Kalshi pins `min_ts` throughout the walk. Subsequent
polls overlap five minutes. Older delayed upstream inserts can still be missed;
no exactly-once upstream completeness claim is made. Polymarket's upstream minimum
trade-size filter also applies. There is no wide global trade collector yet.

Polymarket v2 public rows do not expose a unique fill ID. Identity combines the
execution fields and a per-scan occurrence count, retained across page checkpoints.
This preserves identical rows within a stable newest-first walk and deduplicates
repeat polls. Identical fills cannot be independently distinguished or audited as
on-chain log indices; feed reorganization/correction remains a limitation. Wallet
addresses are public proxy wallets, not identities or verified linked accounts.
The wallet summary covers the anomaly window only, not account age or full history.

Kalshi `taker_outcome_side` and `taker_book_side` encode **the same directional bit**:
YES/bid is positive YES exposure, NO/ask negative. They must not be multiplied.
Block trades are excluded from order-flow imbalance. No other user's account
profile can be constructed from the public tape. Polymarket signals are grouped by
outcome token; buying NO is not pooled with buying YES.

All detector inputs satisfy both `event_time <= as_of` and `received_at <= as_of`.
Rule snapshots must have been observed by `as_of`. Unchanged rules reuse the existing version. Later intake can carry an older
`published_at`, but cannot enter the detection-time timeline retroactively.
`first_seen_at` is our first receipt, not first public availability. Publication
verification is a reviewer assertion with a required note, not automated fact checking.

`anomaly_score` is a weighted heuristic: volume spike 50%, directional
imbalance 30%, within-window price change 20%. Direction/price components require
five observations. `evidence_quality` starts at 30, adds 15 for observed rules and
15 for sufficient baseline; this is preliminary and does not certify completeness.
`investigation_priority` combines anomaly, quality and category tier. **None of
these measures is an insider-trading probability.** No outcomes or realized PnL are
used to score a detection.

No historical executable order books are collected yet. Price change is not proof
of a sweep, depth consumption, persistence, information advantage or causation.
There is no peer-market calibration, automatic news/sports ingestion, wallet history
expansion, verified cross-platform rule mapping, cross-platform lead/lag detector,
post-resolution backtest, or seven-day threshold calibration in this implementation.
These remain necessary before the proposed full investigation service is accepted.

## API and CLI

| Operation | Route |
| --- | --- |
| Database reachability | `GET /health` |
| Completeness diagnostics | `GET /coverage` |
| Catalog (keyset pagination) | `GET /markets?venue=polymarket&after=...` |
| Cases (keyset pagination) | `GET /cases?after=...` |
| Case or preserved version | `GET /cases/{id}?version=1` |
| Markdown dossier | `GET /cases/{id}/report` |
| Immutable raw evidence (hash verified) | `GET /evidence/{raw_id}` |
| Reproduce detectors | `POST /replay` with `venue`, `market_id`, timezone-aware `as_of` |
| Review | `POST /cases/{id}/review` with `status`, `note`, `reviewer` |
| Manual information | `POST /information` with `venue`, `market_id`, `source_url`, `title`, `content`, optional time fields |
| Attach later investigation evidence | `POST /cases/{id}/information/{information_id}` |

Use the Polymarket **condition ID** or Kalshi **ticker** for trade, replay and case
information keys. Market catalog IDs are Polymarket Gamma IDs. Intake does not fetch
the supplied URL; retain the text and verify it independently. Evidence revisions
are new records and attachments, not overwrites.

```sh
python -m surveillance.cli coverage
python -m surveillance.cli verify
python -m surveillance.cli replay --venue kalshi --market TICKER --as-of '2026-10-28T12:00:00+00:00'
python -m surveillance.cli report --case CASE_ID > case.md
```

One worker processes bounded pages sequentially and shares a conservative request
interval; actual polling frequency depends on backlog and endpoint latency. Multiple
workers can claim disjoint jobs, but rate limiting is process-local; do not scale
workers without a shared rate budget. No WebSocket authentication is configured.
Reports expose REST sampling and unavailable order-book coverage explicitly.

Schema initialization is idempotent through version 2; future incompatible changes need
an explicit versioned migration. Use a dedicated database, not the dashboard database.
The single worker performs bounded hourly retention: cases/coverage/paused jobs expire
at 7 days, trades/unreferenced raw at 8 days, with retained-case inputs and current
catalog/rules pinned. Manual information remains retained. Deleted database pages
are reused rather than immediately shrinking files. Cleanup batch limits and pinned
references can extend retention. Do not run multiple archive writers during cleanup.

Automatic candidates coalesce for one hour per contract/outcome/window, unless the
anomaly score rises by 20 points. Explicit replay is not coalesced. Replay is capped
at 50,000 observed trades: excess produces an explicit capacity error (HTTP 413)
without a partial score. Configure `SURVEILLANCE_REPLAY_MAX_TRADES` only after measuring
memory. `SURVEILLANCE_RETENTION_DAYS` controls test-data retention (default 7).

See `deploy/README.md` and `docs/surveillance-capacity-2026-10-28.md` for the local
machine deployment and measured costs. The deployment uses 20 contracts per venue.

## Validation

```sh
pip install -r surveillance/requirements.txt
python -m compileall -q surveillance
# Unit-only run skips PostgreSQL integration tests when the variable is absent.
# Full acceptance requires a disposable PostgreSQL instance with CREATE SCHEMA rights:
export SURVEILLANCE_TEST_DATABASE_URL='postgresql://USER:PASSWORD@127.0.0.1:5432/surveillance_test'
python -m unittest discover -s surveillance/tests -v
```

Every integration test creates and drops only its own random schema. CI supplies
PostgreSQL 17. Tests cover pagination across worker restarts, duplicate fill
multiplicity, transaction rollback, lease expiry/fencing, archive checksums,
future-data exclusion, rule replay, API auth, versioned review and later evidence.

Interface references verified on 2026-10-28:

- [Polymarket Data API v2](https://docs.polymarket.com/api-reference/data-api/overview)
- [Polymarket trade feed](https://docs.polymarket.com/api-reference/feeds/list-trades)
- [Polymarket keyset catalog](https://docs.polymarket.com/api-reference/markets/list-markets-keyset-pagination)
- [Kalshi public trades](https://docs.kalshi.com/api-reference/market/get-trades)

## Event review and wallet self-history (schema 2)

Verified manual information (`publication_time_verified=true`, `published_at`,
`verification_note`) now queues a post-disclosure review. This does **not** activate
an automatic news feed or change real-time detection scores. Query the job through
`GET /coverage`, then fetch its `case_id` via the existing case/report endpoints.
An invalid/expired input or a work cap completes the job with `review_unavailable`;
there is no partial score and no endless retry of an immutable review cutoff.

Reviews use 1h/6h/1d/3d/7d windows before the publication anchor, with exact boundary
fragments. Contract/outcome totals remain separate. One native event ID groups known
siblings into a versioned case, keyed by venue/event/publication time. This is neither
cross-platform equivalence nor a proof that related contracts settle identically.
At most 20 contracts / 20,000 aggregate bins / 50,000 boundary fills / 4,096 evidence
receipts are admitted per review. Excess is explicit. For larger families use
`POST /event-reviews/{information_id}?contract_only=true` or CLI `--contract-only`.

`POST /event-reviews/{information_id}` refreshes after a backfill or aggregation
finishes, using a fresh actual knowledge cutoff. A completed report can contain
`pending_aggregation` or `unknown_or_expired`; sparse/missing bins are never zero-filled.
`sampled_no_trades` requires retained, fully referenced, zero-fill API walks covering
all full bins; it describes REST observations, never guaranteed upstream completeness.
The publication anchor must be verified independently and need not be the earliest
public disclosure. Uncalibrated review scores are `null`.

Five-minute trade bins are sparse and versioned by actual materialization time. Late
fills append a correction without rewriting past versions. The global worker job
processes at most 500 dirty bins per claim every 30 seconds. Bootstrapping indexes the
retained seven-day trade window once; historical investigations can explicitly queue
older retained source rows:

```sh
python -m surveillance.cli aggregate-market --venue polymarket --market CONDITION_ID --start '2026-01-01T00:00:00Z' --end '2026-01-08T00:00:00Z'
python -m surveillance.cli review-event --information INFORMATION_ID --contract-only
```

`GET /aggregates?venue=…&market_id=…&start=…&end=…&as_of=…` reads the latest version
known at that cutoff (maximum seven-day range; explicit result cap). `known_at` is
when the worker computed the bucket, not exchange event time or first receipt time.

New Polymarket automatic cases may queue one public-wallet enrichment, ranked by
observed anomaly-window cash. Admission is limited to four wallets per hour globally,
and each walk to two pages / 1,000 fills from seven days before the alert window until
the alert cutoff, with actual later receipt times. Kalshi never gets wallet profiles.
`GET /wallet-profiles?case_id=…` returns the queued/completed/truncated state. A within-wallet
cash ratio requires a complete requested walk, at least 20 baseline fills across two
observed dates, and current-window fills. Insufficient/truncated history returns
`null`, not zero. Gross contract concentration is descriptive; no net position,
profit, account creation time, person identity or wallet clustering is inferred.
Profiles append a case version while preserving its original scores and human review.

Aggregates, walk receipts and wallet profiles share the seven-day retention and
existing 20 GiB database / 5 GiB raw admission budgets. FIFO eviction removes derived
rows referencing expired receipts; copied case inputs retain their raw pins until
case expiry or capacity eviction. These are admission budgets, not filesystem quotas.
CUSUM/EWMA, statistical threshold calibration, automatic public-information feeds,
and cross-platform rule equivalence remain outside this implementation.

Run `python -m surveillance.research.benchmark_review` inside the API container for
a disposable isolated-schema benchmark of the actual SQL/materialization/review path.
