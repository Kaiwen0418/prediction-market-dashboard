"""Read-only public API smoke in a disposable PostgreSQL schema, never live jobs."""
import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo
from surveillance.config import Settings
from surveillance.storage import Store
from surveillance.worker import Worker
from surveillance.retrospective import discover,run


async def main():
    dsn=os.environ['SURVEILLANCE_TEST_DATABASE_URL'];schema='retro_smoke_'+uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(dsn) as c:await c.execute(f'CREATE SCHEMA "{schema}"')
    settings=Settings(make_conninfo(dsn,options=f'-csearch_path={schema}'),Path('/unused'),review_max_pages=4)
    store=Store(settings.database_url);await store.initialize();results=[]
    try:
        with tempfile.TemporaryDirectory() as directory:
            from dataclasses import replace
            worker=Worker(replace(settings,raw_dir=Path(directory)))
            try:
                for venue in ('polymarket','kalshi'):
                    await store.enqueue('discover:'+venue,'settlement_discovery',venue,{'head':True})
                    job=await store.claim();await discover(worker,job);await store.release(job,3600)
                    reviews=await store.fetch("""SELECT id,market_id,document FROM surveillance_retrospectives WHERE venue=%s
                        AND (document->>'requested_end')::timestamptz-(document->>'requested_start')::timestamptz<interval '2 days'
                        ORDER BY (document->'market'->>'volume')::numeric DESC LIMIT 1""",(venue,))
                    if not reviews:
                        results.append(dict(venue=venue,status='no_short_market_in_head'));continue
                    r=reviews[0]
                    await store.enqueue('review:'+venue,'retrospective',venue,dict(review_id=r['id'],market_id=r['market_id']))
                    job=await store.claim()
                    for _ in range(12):
                        saved=(await store.fetch('SELECT enabled,checkpoint FROM surveillance_jobs WHERE id=%s',(job['id'],)))[0]
                        if not saved['enabled']:break
                        job['checkpoint']=saved['checkpoint'];await run(worker,job)
                    state=(await store.fetch('SELECT status,document FROM surveillance_retrospectives WHERE id=%s',(r['id'],)))[0]
                    slices=await store.fetch("SELECT document->>'input_fills' AS fills,document->>'input_status' AS status,jsonb_array_length(document->'episodes') AS episodes FROM surveillance_review_slices WHERE review_id=%s",(r['id'],))
                    results.append(dict(venue=venue,market_id=r['market_id'],title=r['document']['market']['title'],
                                        status=state['status'],completion=state['document'].get('completion'),slices=slices))
                    await store.release(job,3600)
            finally:await worker.collector.close()
        print(json.dumps(results,indent=2))
    finally:
        async with await psycopg.AsyncConnection.connect(dsn) as c:await c.execute(f'DROP SCHEMA "{schema}" CASCADE')


if __name__=='__main__':asyncio.run(main())
