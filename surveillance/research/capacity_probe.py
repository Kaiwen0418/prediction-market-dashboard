"""Explicit repair/probe for an already stopped worker; never prints evidence IDs."""
import asyncio,argparse,json,time
from pathlib import Path
import hashlib
import psycopg
from psycopg.rows import dict_row
from surveillance.storage import Store
from surveillance.config import Settings
from surveillance.capacity import LOCK,index_legacy_cases,enforce


async def main(repair):
    settings=Settings.env();store=Store(settings.database_url)
    if not repair:raise ValueError('Requires --repair with the collection worker stopped')
    started=time.monotonic();await store.initialize()
    async with await psycopg.AsyncConnection.connect(store.dsn,autocommit=True,row_factory=dict_row) as c:
        await c.execute("SET statement_timeout='15s'")
        indexed=0
        for step in range(150):
            await c.execute('SELECT pg_advisory_lock(%s)',(LOCK,))
            try:result=await index_legacy_cases(c)
            finally:await c.execute('SELECT pg_advisory_unlock(%s)',(LOCK,))
            indexed+=result['indexed']
            if step%10==0:print(json.dumps(dict(indexed=indexed,pending=result['pending'])),flush=True)
            if not result['pending']:break
        if result['pending']:raise ValueError('Backfill budget exhausted; rerun explicitly')
        await c.execute('ANALYZE surveillance_cases(evidence_raw_ids,evidence_indexed,created_at)')
        rows=await (await c.execute('SELECT id,received_at FROM surveillance_raw ORDER BY received_at,id LIMIT 500')).fetchall()
        ids=[r['id'] for r in rows];cutoff=max(r['received_at'] for r in rows)
        await c.execute('SET enable_seqscan=off');await c.execute('SET enable_indexscan=off')
        plan=(await (await c.execute('''EXPLAIN (ANALYZE,FORMAT JSON) SELECT id FROM surveillance_cases WHERE created_at<=%s
            UNION ALL SELECT id FROM surveillance_cases WHERE evidence_raw_ids && %s
            UNION ALL SELECT id FROM surveillance_cases WHERE evidence_observation_ids &&
                (SELECT array_agg(id) FROM surveillance_observations WHERE raw_ids && %s)''',(cutoff,ids,ids))).fetchone())['QUERY PLAN'][0]
        def nodes(p):return [p.get('Relation Name')]+[name for child in p.get('Plans',[]) for name in nodes(child)]
        assert 'surveillance_trades' not in nodes(plan['Plan'])
        print(json.dumps(dict(indexed_cases=indexed,backfill_seconds=time.monotonic()-started,
            dependency_query_ms=plan['Execution Time'],relations=nodes(plan['Plan']))),flush=True)
    for step in range(12):
        result=await enforce(store,settings)
        print(json.dumps(dict(recovery_pass=step,**result),default=str),flush=True)
        if not result['blocked']:break
        if result.get('error'):raise RuntimeError('Bounded recovery stopped: '+result['error'])
    print(json.dumps(dict(source_sha256={name:hashlib.sha256((Path('surveillance')/name).read_bytes()).hexdigest()
        for name in ('capacity.py','schema.sql','maintenance.py')})),flush=True)
    if result['blocked']:raise RuntimeError('Recovery pass budget exhausted; dataset remains blocked')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repair',action='store_true')
    asyncio.run(main(parser.parse_args().repair))
