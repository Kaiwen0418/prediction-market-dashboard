"""Compare eager catalog loading with bounded streaming in isolated schemas."""
import argparse
import asyncio
import json
import os
import resource
import time
import uuid
from datetime import datetime, timezone

import psycopg
from psycopg.conninfo import make_conninfo

from .discovery import select, Selector
from .storage import Store


async def run(count, mode):
    base = os.environ["SURVEILLANCE_DATABASE_URL"]
    schema = "surveillance_catalog_bench_" + uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(base) as c:
        await c.execute(f'CREATE SCHEMA "{schema}"')
    try:
        store = Store(make_conninfo(base, options=f"-csearch_path={schema}"))
        await store.initialize()
        async with store.connection() as c:
            await c.execute("""INSERT INTO surveillance_markets(venue,id,document,observed_at)
                SELECT 'kalshi','CAT'||n,jsonb_build_object('id','CAT'||n,'venue','kalshi','condition_id',NULL,
                    'closed',false,'title',CASE WHEN n%%10=0 THEN 'Policy announcement' ELSE 'Other market' END,
                    'volume',(n%%10000)::text,'rules',jsonb_build_object('description',repeat('benchmark rule ',100))),now()
                FROM generate_series(1,%s) AS n""", (count,))
        at = datetime(2026,10,28,12,tzinfo=timezone.utc)
        started = time.perf_counter()
        if mode == "eager":
            rows = await store.fetch("SELECT document FROM surveillance_markets")
            chosen = select([r["document"] for r in rows], 100, at=at)
        else:
            selector = Selector(100, at=at)
            async with store.connection() as c:
                async with c.cursor(name="catalog_benchmark") as cursor:
                    cursor.itersize = 256
                    await cursor.execute("SELECT document FROM surveillance_markets")
                    async for row in cursor:
                        selector.add(row["document"])
            chosen = selector.result()
        return dict(workload="synthetic 1.4KB rule documents; catalog selection only", mode=mode,
                    contracts=count, selected=len(chosen), selection_seconds=round(time.perf_counter()-started,3),
                    max_rss_mib=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1),
                    selected_ids=[m["id"] for m in chosen])
    finally:
        async with await psycopg.AsyncConnection.connect(base) as c:
            await c.execute(f'DROP SCHEMA "{schema}" CASCADE')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--contracts', type=int, default=100000)
    p.add_argument('--mode', choices=['eager','stream'], required=True)
    args=p.parse_args()
    if args.contracts<1:p.error('Positive contract count required')
    print(json.dumps(asyncio.run(run(args.contracts,args.mode)),indent=2))


if __name__=='__main__': main()
