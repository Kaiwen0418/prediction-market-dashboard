"""Isolated-schema synthetic normalized archive + 50k-fill retrospective benchmark."""
import asyncio
import json
import hashlib
import os
import resource
import tempfile
import time
import uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from surveillance.storage import Store,RawArchive
from surveillance.research_archive import capture,read_tape
from surveillance.leadlag import analyze


async def main():
    dsn=os.environ['SURVEILLANCE_TEST_DATABASE_URL'];schema='retro_benchmark_'+uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(dsn) as c:await c.execute(f'CREATE SCHEMA "{schema}"')
    store=Store(make_conninfo(dsn,options=f'-csearch_path={schema}'))
    try:
        await store.initialize();base=datetime.now(timezone.utc)-timedelta(days=10);fills=[]
        for i in range(50000):
            at=base+timedelta(seconds=i*12)
            price=.2 if (i//1000)%2==0 else .45
            fills.append(dict(id=hashlib.sha256(str(i).encode()).hexdigest(),venue='polymarket',market_id='bench',outcome='yes',token_id='yes',
                event_time=at.isoformat(),received_at=datetime.now(timezone.utc).isoformat(),price=str(price),quantity='100',
                direction=1 if i%3 else -1,wallet='0x'+hashlib.sha256(str(i%300).encode()).hexdigest()[:40],cash_price=str(price),cash_notional=str(price*100)))
        with tempfile.TemporaryDirectory() as directory:
            archive=RawArchive(directory);start=time.perf_counter()
            async with store.connection() as c:
                for offset in range(0,len(fills),1000):
                    raw=archive.write('polymarket','synthetic',{},200,json.dumps(fills[offset:offset+1000]).encode())
                    await capture(c,fills[offset:offset+1000],raw)
            ingest=time.perf_counter()-start
            start=time.perf_counter();rows,refs=await read_tape(store,'polymarket','bench',base.isoformat(),(base+timedelta(days=8)).isoformat())
            read=time.perf_counter()-start;start=time.perf_counter()
            report=analyze(rows,base.isoformat(),(base+timedelta(days=8)).isoformat())
            analysis=time.perf_counter()-start
            sizes=await store.fetch("SELECT pg_total_relation_size('surveillance_research_tape') AS physical_bytes,(SELECT logical_bytes FROM surveillance_research_budget WHERE name='surveillance_research_tape') AS budget_bytes")
            print(json.dumps(dict(fills=len(rows),archive_insert_seconds=ingest,read_seconds=read,analysis_seconds=analysis,
                peak_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**sizes[0],
                report_bytes=len(json.dumps(report).encode()),episodes=report['episodes_detected'],
                constraints='Synthetic 50k fills, 300 wallets, one CPU container; RSS includes fixture, JSON and Parquet; not live throughput guarantee'),indent=2))
    finally:
        async with await psycopg.AsyncConnection.connect(dsn) as c:await c.execute(f'DROP SCHEMA "{schema}" CASCADE')


if __name__=='__main__':asyncio.run(main())
