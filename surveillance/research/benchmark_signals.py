"""Disposable-schema cost probe; never modifies the running surveillance dataset."""
import asyncio
from datetime import datetime,timedelta,timezone
import json
from statistics import median
from time import perf_counter
import uuid
import psycopg
from psycopg.conninfo import make_conninfo

from surveillance.config import Settings
from surveillance.storage import Store
from surveillance.normalization import trade,now
from surveillance.detectors import evaluate
from surveillance.longitudinal import ingest_daily,find_accumulations,DAILY_LIMIT


async def main():
    base=Settings.env().database_url
    schema='surveillance_benchmark_'+uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(base) as c:
        await c.execute(f'CREATE SCHEMA "{schema}"')
    store=Store(make_conninfo(base,options=f'-csearch_path={schema}'))
    try:
        await store.initialize()
        start=perf_counter()
        async with store.connection() as c:
            await c.execute("""INSERT INTO surveillance_wallet_daily
                SELECT '0x'||lpad(to_hex(i),40,'0'),'benchmark-market','yes','Yes',
                    (now() AT TIME ZONE 'UTC')::date,now(),now(),now(),1,5,0,10,0,5,ARRAY['benchmark'],true
                FROM generate_series(1,%s) i""",(DAILY_LIMIT,))
        fill_seconds=perf_counter()-start
        cutoff=datetime.now(timezone.utc).replace(second=0,microsecond=0)
        rows=[trade('polymarket',dict(condition_id='benchmark-market',token_id='yes',outcome='Yes',side='BUY',
              price='.5',size='10',timestamp=int(cutoff.timestamp())-1,proxy_wallet='0x'+format(i,'040x'),transaction_hash='benchmark'),now()) for i in range(1,1001)]
        latencies=[]
        for _ in range(7):
            start=perf_counter()
            async with store.connection() as c:await ingest_daily(c,rows,'benchmark')
            latencies.append(perf_counter()-start)
        sizes=(await store.fetch("SELECT count(*) AS rows,pg_total_relation_size('surveillance_wallet_daily') AS bytes FROM surveillance_wallet_daily"))[0]
        start=perf_counter();await find_accumulations(store);scan_seconds=perf_counter()-start
        tape=[dict(rows[i%1000],id=str(i),event_time=(cutoff-timedelta(seconds=i*46800/50000)).isoformat()) for i in range(50000)]
        timings=[]
        for _ in range(3):
            start=perf_counter();signals=evaluate(tape,cutoff.isoformat(),knowledge_cutoff=now(),coverage=[(cutoff-timedelta(hours=13),cutoff)]);timings.append(perf_counter()-start)
            assert len(signals)==3 and signals[2]['trade_count']>3000,'Benchmark must evaluate retained fills'
        print(json.dumps(dict(measured_at=now(),daily_row_limit=DAILY_LIMIT,daily_storage=sizes,
            synthetic_seed_seconds=fill_seconds,batch_1000_fills_at_capacity_seconds=dict(median=median(latencies),max=max(latencies)),
            slow_scan_at_capacity_seconds=scan_seconds,detector_50000_fills_seconds=dict(median=median(timings),max=max(timings)),
            limitations=['Synthetic disposable schema on shared VM; not a sustained production growth forecast',
                          'Daily cells are hard-admission capped; cases, evidence arrays and WAL have separate costs',
                          'Existing cells continue at cap; unseen cells are skipped with hourly coverage telemetry']),indent=2))
    finally:
        async with await psycopg.AsyncConnection.connect(base) as c:
            await c.execute(f'DROP SCHEMA "{schema}" CASCADE')


if __name__=='__main__':asyncio.run(main())
