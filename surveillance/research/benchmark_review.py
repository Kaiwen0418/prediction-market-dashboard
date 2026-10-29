"""Disposable isolated-schema benchmark of the actual review implementation."""
import asyncio
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import resource
import tempfile
import time
import uuid

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from surveillance.storage import Store,RawArchive
from surveillance.aggregates import materialize
from surveillance.event_review import build_review
from surveillance.normalization import now


async def main():
    base=os.environ['SURVEILLANCE_DATABASE_URL']
    schema='surveillance_bench_'+uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(base) as c:
        await c.execute(f'CREATE SCHEMA "{schema}"')
    try:
        store=Store(make_conninfo(base,options=f'-csearch_path={schema}'))
        await store.initialize()
        with tempfile.TemporaryDirectory() as folder:
            raw=RawArchive(folder).write('polymarket','synthetic benchmark',{},0,b'50000 synthetic uniform fills / seven days; not exchange evidence')
            anchor=datetime.now(timezone.utc).replace(minute=0,second=37,microsecond=123456)-timedelta(hours=1)
            start=anchor-timedelta(days=7)
            t=time.perf_counter()
            async with store.connection() as c:
                await store.insert_raw(c,raw)
                await c.execute('''INSERT INTO surveillance_trades
                    SELECT 'polymarket',g::text,'bench','yes',%s+g*interval '12 seconds',%s,
                        jsonb_build_object('id',g::text,'price','0.5','quantity','10','direction',1,
                            'token_id','token-yes','outcome','yes','market_id','bench'),%s
                    FROM generate_series(0,49999) g''', (start,raw['received_at'],raw['id']))
                await c.execute('''INSERT INTO surveillance_dirty_bins
                    SELECT DISTINCT venue,market_id,document->>'token_id',
                        to_timestamp((floor(extract(epoch FROM event_time)/300)+1)*300) FROM surveillance_trades''')
                await c.execute('''INSERT INTO surveillance_information(id,venue,market_id,document,raw_id)
                    VALUES('notice','polymarket','bench',%s,%s)''',
                    (Jsonb(dict(title='synthetic notice',published_at=anchor.isoformat(),publication_time_verified=True)),raw['id']))
                # Exercise overlapping walks and SQL interval union (>256 rows).
                await c.execute('''INSERT INTO surveillance_walks
                    SELECT g::text,'polymarket','bench',%s,%s,%s,ARRAY[%s]::text[],true,50000
                    FROM generate_series(1,300) g''', (start,anchor,now(),raw['id']))
            intake=time.perf_counter()-t
            versions=0;passes=0;t=time.perf_counter()
            while True:
                result=await materialize(store)
                passes+=1;versions+=result['appended_versions']
                if not result['processed_bins']:break
            aggregate_seconds=time.perf_counter()-t
            t=time.perf_counter();doc=await build_review(store,'notice',now());review_seconds=time.perf_counter()-t
            sizes=await store.fetch('''SELECT relname,pg_total_relation_size(c.oid) AS bytes FROM pg_class c
                JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema()
                AND relkind='r' ORDER BY relname''')
            actual=doc['contracts'][0]['windows'][-1]['outcomes'][0]['fills']
            assert actual==50000,actual
            print(json.dumps(dict(kind='synthetic implementation benchmark',fills=50000,span_days=7,
                aggregate_versions=versions,aggregate_passes=passes,intake_seconds=intake,
                aggregate_seconds=aggregate_seconds,review_seconds=review_seconds,relation_bytes=sizes,
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                review_windows=doc['contracts'][0]['windows'],generated_at=now(),
                caveats=['One synthetic contract / one outcome; not a whole-platform throughput estimate',
                    'API container limited to 1 CPU / 512 MiB; PostgreSQL shared with live test services',
                    'Source tables, JSON payloads, indexes, raw receipts and cases measured separately',
                    'No new realtime classification accuracy inferred']),indent=2))
    finally:
        async with await psycopg.AsyncConnection.connect(base) as c:
            await c.execute(f'DROP SCHEMA "{schema}" CASCADE')


if __name__=='__main__':
    asyncio.run(main())
