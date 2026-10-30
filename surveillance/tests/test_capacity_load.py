"""Capacity regression: indexed dependencies, bounded cancellation and reusable pages."""
import os,unittest
from dataclasses import replace
from unittest.mock import patch
import psycopg
from surveillance.tests import test_postgres as pg
from surveillance.normalization import now,trade
from surveillance.tests.test_core import poly
from surveillance.capacity import evict_batch,enforce,index_legacy_cases,pressured,free_space


@unittest.skipUnless(os.getenv('SURVEILLANCE_TEST_DATABASE_URL'),'PostgreSQL test DSN required')
class CapacityLoadTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=pg.PostgresTests.asyncSetUp
    asyncTearDown=pg.PostgresTests.asyncTearDown
    job=pg.PostgresTests.job

    async def raw(self,key='old'):
        raw=self.archive.write('polymarket','test',{},200,key.encode(),'2020-01-01T00:00:00+00:00')
        await self.store.raw(raw);return raw

    async def test_index_covers_legacy_fill_and_old_review_version(self):
        raw=await self.raw();j=await self.job()
        t=dict(trade('polymarket',poly(),now()),id='legacy-fill')
        await self.store.commit_page(j,raw,{},trades=[t])
        await self.store.save_case(dict(id='old-version',venue='polymarket',market_id='c1',replay_input_ids=['legacy-fill']))
        row=(await self.store.fetch('SELECT evidence_raw_ids FROM surveillance_cases'))[0]
        self.assertEqual(row['evidence_raw_ids'],[raw['id']])
        # Enrichment omits the old reference; the historical version still pins it.
        await self.store.update_dossier(dict(id='old-version',venue='polymarket',market_id='c1',status='candidate',replay_raw_ids=[]))
        async with self.store.connection() as c:self.assertEqual(await evict_batch(c,1),1)
        self.assertFalse(await self.store.fetch('SELECT * FROM surveillance_cases'))
        self.assertFalse(await self.store.fetch('SELECT * FROM surveillance_case_versions'))

    async def test_backfill_commits_bounded_batches_before_eviction(self):
        raw=await self.raw()
        for i in range(5):await self.store.save_case(dict(id=str(i),venue='polymarket',market_id='c1',replay_raw_ids=[raw['id']]))
        async with self.store.connection() as c:
            await c.execute("UPDATE surveillance_cases SET evidence_indexed=false,evidence_raw_ids='{}'")
        async with self.store.connection() as c:
            first=await index_legacy_cases(c,2)
        self.assertEqual(first,dict(indexed=2,pending=True))
        self.assertEqual((await self.store.fetch('SELECT count(*) AS n FROM surveillance_cases WHERE evidence_indexed'))[0]['n'],2)
        async with self.store.connection() as c:
            self.assertFalse((await index_legacy_cases(c,10))['pending'])
            await evict_batch(c,1)
        self.assertFalse(await self.store.fetch('SELECT * FROM surveillance_cases'))

    async def test_real_statement_timeout_releases_evidence_lock(self):
        await self.raw()
        async def slow(c,*args,**kwargs):
            await c.execute('SELECT pg_sleep(.2)')
        with patch('surveillance.capacity.QUERY_TIMEOUT_MS',50),patch('surveillance.capacity.free_space',slow):
            result=await enforce(self.store,replace(self.settings,raw_max_bytes=1))
        self.assertEqual(result['error'],'QueryCanceled');self.assertTrue(result['blocked'])
        async with self.store.connection(exclusive=True) as c:
            self.assertEqual((await (await c.execute('SELECT 1 AS n')).fetchone())['n'],1)

    async def test_allocated_free_pages_do_not_retrigger_live_watermark(self):
        settings=replace(self.settings,database_max_bytes=1000,raw_max_bytes=1000)
        self.assertFalse(pressured(dict(database_bytes=900,database_used_bytes=500,raw_bytes=0),settings))
        self.assertTrue(pressured(dict(database_bytes=1001,database_used_bytes=500,raw_bytes=0),settings))
        self.assertTrue(pressured(dict(database_bytes=900,database_used_bytes=801,raw_bytes=0),settings))

    async def test_indexed_plan_has_no_trade_relation_scan(self):
        raw=await self.raw()
        await self.store.save_case(dict(id='case',venue='polymarket',market_id='c1',replay_raw_ids=[raw['id']]))
        class Trace:
            def __init__(self,c):self.c=c;self.query=None
            def __getattr__(self,name):return getattr(self.c,name)
            async def execute(self,query,params=()):
                if isinstance(query,str) and query.startswith('CREATE TEMP TABLE capacity_cases'):
                    self.query=(query.partition(' AS')[2],params)
                return await self.c.execute(query,params)
        async with self.store.connection() as c:
            traced=Trace(c)
            await evict_batch(traced,1)
            plan=await (await c.execute('EXPLAIN (FORMAT JSON) '+traced.query[0],traced.query[1])).fetchall()
        self.assertNotIn('surveillance_trades',str(plan))


    async def test_observation_indexing_does_not_rescan_large_case_per_observation(self):
        from psycopg.types.json import Jsonb
        raw=await self.raw()
        async with self.store.connection() as c:
            await c.execute("""INSERT INTO surveillance_observations
                SELECT i::text,'polymarket',NULL,now()-interval '1 hour',now(),now(),ARRAY[%s],true
                FROM generate_series(1,20000) i""",(raw['id'],))
            await c.execute("SET LOCAL statement_timeout='1500ms'")
            doc=dict(id='large',venue='polymarket',market_id='c1',replay_raw_ids=[raw['id']],
                observation_ids=['1'],padding=['payload '*20]*3000)
            await c.execute("INSERT INTO surveillance_cases(id,venue,market_id,status,document) VALUES('large','polymarket','c1','candidate',%s)",(Jsonb(doc),))
        rows=await self.store.fetch("SELECT evidence_raw_ids FROM surveillance_cases WHERE id='large'")
        self.assertEqual(rows[0]['evidence_raw_ids'],[raw['id']])

    async def test_api_returns_retryable_status_during_evidence_lock(self):
        import httpx
        from surveillance.api import create_app
        app=create_app(replace(self.settings,api_token='test-token'))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':'Bearer test-token'}) as client:
            async with self.store.connection(exclusive=True):
                response=await client.get('/health')
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.headers['Retry-After'],'5')
            self.assertEqual((await client.get('/health')).status_code,200)

    async def test_space_measurement_after_deletion_allows_api_reads(self):
        import asyncio
        from surveillance.capacity import free_space as original
        await self.raw()
        calls=0
        async def inspect(c,details=False):
            nonlocal calls
            calls+=1
            if calls==2:
                self.assertEqual((await asyncio.wait_for(self.store.fetch('SELECT 1 AS n'),1))[0]['n'],1)
            return await original(c,details)
        with patch('surveillance.capacity.free_space',inspect):
            result=await enforce(self.store,replace(self.settings,raw_max_bytes=1),batch_limit=1,max_batches=1)
        self.assertIsNone(result['error']);self.assertEqual(calls,2)
