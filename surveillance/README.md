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
- Default budget: 100 selected contracts per venue, with 20% six-hour rotating
  exploration. Rules/category keywords and proximity provide an initial ranking;
  no category is excluded from discovery. Paused jobs preserve cursors. Active
  candidates cause an immediate collection request within the selected budget.
- Versioned 1-minute / 5-minute / 1-hour volume, direction and price-change
  detectors. Per-market median/MAD over 12 preceding windows. At least six fully sampled, cash-complete
  baseline windows are required for the cash-spike component; observed zero is valid, unknown is not.
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

Cold deep trade bootstrap requests one hour; wide bootstrap requests five minutes.
The detector reads up to 13 hours of retained observations, not all history. A newest-first walk stops
only after crossing its lower bound, including every row at the boundary second.
Polymarket condition feeds ignore time filters: the worker walks the cursor and
applies the boundary locally. Kalshi pins `min_ts` throughout the walk. Subsequent
polls overlap five minutes. Older delayed upstream inserts can still be missed;
no exactly-once upstream completeness claim is made. Polymarket's upstream minimum
trade-size filter also applies. Independent paginated global trade collectors are enabled on both venues.

Polymarket v2 public rows do not expose a unique fill ID. Identity combines the
execution fields and a per-scan occurrence count, retained across page checkpoints.
This preserves identical rows within a stable newest-first walk and deduplicates
repeat polls. Identical fills cannot be independently distinguished or audited as
on-chain log indices; feed reorganization/correction remains a limitation. Wallet
addresses are public proxy wallets, not identities or verified linked accounts.
The original alert wallet summary covers its anomaly window; bounded multi-day
rollups and optional self-history enrichment add separate observations, not account age.

Kalshi `taker_outcome_side` and `taker_book_side` encode **the same directional bit**:
YES/bid is positive YES exposure, NO/ask negative. They must not be multiplied.
Block trades are excluded from order-flow imbalance. No other user's account
profile can be constructed from the public tape. Polymarket signals are grouped by
outcome token; buying NO is not pooled with buying YES.

Detector inputs satisfy `event_time <= as_of` and `received_at <= knowledge_cutoff`.
Ordinary historical replay defaults `knowledge_cutoff=as_of`. Delayed observations
use an explicitly later knowledge cutoff and retain actual alert creation time.
Rule snapshots must have been observed by the knowledge cutoff. Unchanged rules reuse the existing version. Later intake can carry an older
`published_at`, but cannot enter the detection-time timeline retroactively.
`first_seen_at` is our first receipt, not first public availability. Publication
verification is a reviewer assertion with a required note, not automated fact checking.

`anomaly_score` is a weighted heuristic: cash spike 50%, cash-weighted directional
imbalance 30%, direction-consistent sustained trade-price change 20%. Direction/price
components require five observations. `evidence_quality` reports rule availability,
current sampled coverage, observed baseline count and receipt delay; its heuristic
weights do not certify completeness.
`investigation_priority` combines anomaly, quality and category tier. **None of
these measures is an insider-trading probability.** No outcomes or realized PnL are
used to score a detection.

No historical executable order books are collected yet. Price change is not proof
of a sweep, depth consumption, persistence, information advantage or causation.
There is no peer-market calibration, automatic news/sports ingestion,
verified cross-platform rule mapping, cross-platform lead/lag detector,
population-wide profit backtest, or seven-day threshold calibration in this implementation.
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

Schema initialization is idempotent through version 3; future incompatible changes need
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
machine deployment and measured costs. The deployment uses 100 event-diverse deep contracts per venue plus independent global trade discovery.

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
processes at most 2,000 dirty bins per claim every 30 seconds. Bootstrapping indexes the
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


## Broad discovery and selection correction (schema 3)

Public global trade pagination now runs independently for both venues; it does not
require a deep-selected contract. It starts with a five-minute lookback, overlaps
60 event-time seconds between walks, and saves cursors/counts with the fills in one
transaction. Each claim processes at most two pages. A pending cursor denotes a
walk still being consumed, not a caught-up platform feed. Upstream indexing latency
and revisions older than the overlap remain limitations. `feed_head_at` is the actual
newest returned event; received time is kept separately. Global feeds may contain
combinations or recently closed contracts; deep eligibility still excludes source
closed/settled/nontradable/combo markets.

Deep capacity defaults to 100 per venue. Selection requires one unambiguous native
event ID, caps each event at two contracts, reserves 20% for low-activity exploration,
and allocates the remaining pool across information/sports/civic strata. Ten percent
of capacity can promote previously unselected contracts with observed broad cash
activity. Promotion cash and recent/prior observations are triage inputs, not an
insider score. Low-activity means reported 24h native volume <=1,000, falling back to
reported lifetime volume; venue units differ and are never treated as comparable
cash. Unknown volume is not assumed to be observed zero.

Missing/ambiguous event metadata goes to a bounded enrichment queue instead of being
counted as an independent event. At most 20 active lookup jobs per venue are admitted;
three failures finish an unresolved lookup. Unmapped global trades remain retained.
The selector keeps a bounded candidate pool; when a stratum lacks eligible events,
unused deep capacity falls back to the other available strata and exposes actual
allocation in coverage. Hourly-hash churn was replaced with six-hour exploration
rotation plus a preference for existing selections. A past schedule lowers ranking;
explicit source lifecycle controls eligibility.

Gamma details now use an exact-ID filtered market list with events/tags. Omitted
metadata fields preserve their prior value, per-field source receipt and observation
time; explicit empty values can clear them. Legacy nonempty metadata inherits its
previous index source. These raw references join retention and capacity eviction.
`nominal` no longer matches nomination; ordinary election "win" no longer means P0.
Classification remains a transparent heuristic using structured metadata and words.

The global worker prioritizes wide capture, selection, aggregates and detection over
background metadata/history requests. Deep trade fallback runs every 900 seconds,
rule detail every 1,800 seconds; these are queue delays, not guaranteed poll deadlines.
Cold deep contracts request one hour of history, with incomplete baseline exposed.
The existing 13-hour replay query does not imply that 13 hours were collected.
Use explicit backfill for longer investigations. Global collection remains active
between these fallback requests. Configuration overrides:
`SURVEILLANCE_CONTRACTS`, `SURVEILLANCE_DEEP_POLL_SECONDS`,
`SURVEILLANCE_DETAIL_SECONDS`, `SURVEILLANCE_WIDE_POLL_SECONDS`.

`GET /selection` exposes each current deep contract and its selection reason.
`GET /coverage` distinguishes catalog, broad observations, deep event allocation,
unmapped candidates, page-budget gaps and aggregation backlog. For read-only runtime
snapshots run `python -m surveillance.research.live_coverage` in the API container.
Actual deep count, distinct event count and broad observed contracts are separate.

Deployment stops the sole worker before releasing stale leases, preserving all
checkpoints. SIGTERM cancels the active claim and releases it before shutdown.
`python -m surveillance.cli recover-worker` is an operator command for a stopped sole
worker; never run it against a worker still executing claims. No database reset is
part of deployment. Scout counters retain roughly 30-90 minutes between maintenance
passes, represent deduplicated observed fills, and are disposable under capacity
pressure. They are not used as historical replay scores.


Live probes on 2026-10-29 observed `Cache-Control: public, max-age=300` on
Polymarket global and filtered trade responses. Poll cadence is not source freshness.
Selected response cache headers are retained with the raw receipt; coverage exposes
`wide_freshness` with actual head-event age, receipt age and cursor state. A 200 from
an endpoint, or a completed historical walk, never establishes sub-minute discovery.
No cache-busting parameters or header-based freshness guarantees are assumed.


Exact-ID/condition metadata lookup explicitly retries `closed=true` when the default
open listing is empty, then uses the individual ID endpoint if needed. This preserves
historical investigations and recognizes selected contracts that have just closed;
it never treats an empty open listing as proof that the contract does not exist.


## Cash, observation clocks and multi-day signals (schema 4 / detector v2.0)

Kalshi trade prices remain YES quotes for price comparison, but dollar turnover
uses the taker outcome premium: NO uses its observed NO price or `1 - YES price`.
Unknown taker outcomes produce unknown cash. Existing fill fingerprints do not change.
A one-off migration queues corrected versions of retained Kalshi five-minute bins;
legacy versions remain readable and are marked cash-incomplete.

Completed, fully referenced REST walks append sampled observation intervals in the
same transaction as their checkpoint. The interval ends at the first-page source
head, bounded by receipt time; cached empty pages subtract HTTP Age or max-age.
Pending/legacy walks and missing intervals do not establish zero activity. This
is API sampling evidence, not a guarantee of exchange completeness.

The rolling detector compares twelve equal prior windows; six sampled windows
are needed for the cash-spike component. Current sampling and known cash are
required for automatic case admission. Direction-consistent price persistence is
a trade-price proxy; executable-depth sweeps still cannot be inferred. The worker
uses source-head event windows and actual current knowledge/alert times. Late
upstream inserts older than finite overlap, and multiple price spikes between
polls, can still be missed. No WS or sub-minute latency claim is made.

Outside the 100-contract deep pool, each venue's one-minute scanner considers at
most 5,000 recently observed scout contracts with >=$1,000, queues at most 20
one-off detections, excludes deep detections, applies two contracts per event and
a five-minute repeat cooldown. The scan does not increase the selected pool.
Metadata lookups and activity-based promotion remain separate bounded steps.

Polymarket fills newly inserted into the trade table also update seven retained
UTC dates of wallet/market/outcome cells. Admission is capped at 200,000 cells;
existing cells still update at capacity, while skipped new cells emit hourly
coverage telemetry. Each cell retains <=64 receipt IDs, with truncation explicit.
Hourly slow-accumulation candidates require >=2 observed dates, >=6 hours, >=3
fills, >=$1,000 observed buy cash, and observed buy shares minus sell shares >=80%
of buy shares. These are descriptive candidates with null scores, not an inventory
claim, statistical significance or a complete wallet history.

Verified manual information anchors drive a separate result ledger. At most 20
anchors are processed per hourly pass (60s continuation if paginated); per anchor
<=20 native sibling contracts, <=50,000 fills, and top 50 observed wallets are
considered. Unknown settlements queue <=20 pending one-off detail refreshes globally,
with hourly cooldown and three source failures before stopping. Final outcomes
require a final source status and exact valid outcome prices. Only independent
native events count; the earliest retained verified anchor wins. Mismatches, mixed
exposure, unknown direction and unresolved events remain in the denominator.
Three matching selected events may create a separate null-score review candidate.
No retrospective result changes the original trading alert.

`GET /wallets/{wallet}/patterns?as_of=...` reads ledger versions known by that
cutoff. `POST /replay` accepts an optional `knowledge_cutoff`; default is the event
cutoff, not now. Cases distinguish pre-anchor trade time, receipt time and a real
case created before publication. Event anchors do not prove earliest availability,
and a wallet address does not establish identity, coordination, profit or insider trading.

New summaries/observations share existing 20 GiB DB / 5 GiB raw admission budgets,
seven-day retention and FIFO dependency expiry. Case-pinned observation intervals
survive independent derived-row cleanup; source FIFO still expires dependent cases.
Historical `research.study` intentionally runs frozen v1.1 from
`research/legacy_detector.py`; archived study results are not v2.0 validation.
Run `python -m surveillance.research.benchmark_signals` in the API container for an
isolated 200,000-cell and 50,000-fill cost probe.
