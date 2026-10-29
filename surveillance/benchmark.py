"""Disposable PostgreSQL benchmark; never writes into service tables."""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import resource
import statistics
import tempfile
import time
import uuid

import psycopg
from psycopg.conninfo import make_conninfo

from .investigations import replay
from .normalization import canonical, digest, market
from .storage import RawArchive, Store


def percentile(values, fraction):
    return sorted(values)[min(len(values) - 1, int(len(values) * fraction))]


async def benchmark(contracts, trades_per_contract, replays):
    base = os.environ["SURVEILLANCE_DATABASE_URL"]
    schema = "surveillance_bench_" + uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(base) as c:
        await c.execute(f'CREATE SCHEMA "{schema}"')
    try:
        store = Store(make_conninfo(base, options=f"-csearch_path={schema}"))
        await store.initialize()
        cutoff = datetime.now(timezone.utc).replace(microsecond=0)
        observation = (cutoff - timedelta(seconds=1)).isoformat()
        page_times, replay_times, case_sizes = [], [], []
        with tempfile.TemporaryDirectory(prefix="surveillance-bench-") as folder:
            archive = RawArchive(folder)
            for contract in range(contracts):
                venue = "polymarket" if contract % 2 == 0 else "kalshi"
                key = f"BENCH{contract:04d}"
                await store.enqueue(key, "trades", venue, {"market_id": key})
                job = await store.claim()
                m = market("kalshi", {"ticker": key, "event_ticker": "e", "title": "Policy announcement",
                                     "rules_primary": "Benchmark rule", "status": "open"}, observation)
                m.update(venue=venue, condition_id=key if venue == "polymarket" else None)
                trades = []
                for i in range(trades_per_contract):
                    # Quiet 12h history plus a burst; a case-producing stress fixture.
                    seconds = 30 - i if i < 20 else 90 + (i - 20) * (43000 / max(1, trades_per_contract - 20))
                    row = dict(id=f"{key}-{i}", identity=f"{key}-{i}", venue=venue, market_id=key,
                               outcome="yes", token_id="yes" if venue == "polymarket" else None,
                               price=str(0.3 + 0.02 * (i % 10)), quantity="100" if i < 20 else "10",
                               direction=1, wallet=f"wallet{i % 10}" if venue == "polymarket" else None,
                               transaction_hash=digest([key, i]) if venue == "polymarket" else None,
                               event_time=(cutoff - timedelta(seconds=seconds)).isoformat(),
                               received_at=observation, first_seen_at=observation)
                    trades.append(row)
                body = canonical(trades).encode()
                started = time.perf_counter()
                raw = archive.write(venue, "benchmark://synthetic", {}, 200, body, observation)
                await store.raw(raw)
                await store.commit_page(job, raw, {"completed_at": observation}, markets=[m], trades=trades)
                await store.release(job, 86400)
                page_times.append(time.perf_counter() - started)
            sizes = await store.fetch("""SELECT relname,pg_total_relation_size(relid) AS bytes FROM pg_catalog.pg_statio_user_tables
                WHERE schemaname=current_schema() ORDER BY relname""")
            raw_bytes = sum(p.stat().st_size for p in Path(folder).rglob("*.parquet"))
            for i in range(replays):
                contract = i % contracts
                key = f"BENCH{contract:04d}"
                started = time.perf_counter()
                cases = await replay(store, "polymarket" if contract % 2 == 0 else "kalshi", key, cutoff.isoformat())
                replay_times.append(time.perf_counter() - started)
                case_sizes.extend(len(canonical(case).encode()) for case in cases)
            after = await store.fetch("""SELECT relname,pg_total_relation_size(relid) AS bytes FROM pg_catalog.pg_statio_user_tables
                WHERE schemaname=current_schema() ORDER BY relname""")
            # Repeat an identical response to expose baseline raw duplication overhead.
            raw_repeat = archive.write(venue, "benchmark://synthetic", {}, 200, body, observation)
            archive.read(raw_repeat)
            return dict(workload="synthetic case-producing fixture; not a live throughput guarantee",
                contracts=contracts, trades=contracts * trades_per_contract,
                ingestion_seconds=round(sum(page_times), 3),
                trades_per_second=round(contracts * trades_per_contract / sum(page_times), 1),
                page_p50_ms=round(statistics.median(page_times) * 1000, 2),
                page_p95_ms=round(percentile(page_times, .95) * 1000, 2),
                replay_p50_ms=round(statistics.median(replay_times) * 1000, 2),
                replay_p95_ms=round(percentile(replay_times, .95) * 1000, 2),
                replay_count=replays, max_rss_mib=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                raw_bytes=raw_bytes, raw_bytes_per_trade=round(raw_bytes / (contracts * trades_per_contract), 2),
                relations_before_cases=sizes, relations_after_cases=after,
                case_count=len(case_sizes), case_mean_json_bytes=round(statistics.mean(case_sizes)) if case_sizes else 0)
    finally:
        async with await psycopg.AsyncConnection.connect(base) as c:
            await c.execute(f'DROP SCHEMA "{schema}" CASCADE')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--contracts", type=int, default=200)
    parser.add_argument("--trades-per-contract", type=int, default=1000)
    parser.add_argument("--replays", type=int, default=20)
    args = parser.parse_args()
    if min(args.contracts, args.trades_per_contract, args.replays) < 1:
        parser.error("All workload sizes must be positive")
    print(json.dumps(asyncio.run(benchmark(args.contracts, args.trades_per_contract, args.replays)), indent=2))


if __name__ == "__main__":
    main()
