"""Real query plans and state preservation under a large disabled queue."""
from datetime import datetime,timedelta,timezone
import os
import unittest
from unittest.mock import patch
from psycopg.types.json import Jsonb

from surveillance.tests import test_postgres as pg
from surveillance.storage import CLAIM_SQL
from surveillance.worker import Worker
from surveillance.observation import latest_cutoff,intervals
from surveillance.capacity import enforce,free_space


@unittest.skipUnless(os.getenv('SURVEILLANCE_TEST_DATABASE_URL'),'PostgreSQL test DSN required')
class IoTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=pg.PostgresTests.asyncSetUp
    asyncTearDown=pg.PostgresTests.asyncTearDown

    async def test_real_claim_plan_excludes_disabled_archive_and_preserves_priority(self):
        async with self.store.connection() as c:
            await c.execute("""INSERT INTO surveillance_jobs(id,kind,venue,payload,enabled)
                SELECT 'old:'||i,'detect','polymarket',jsonb_build_object('padding',repeat('x',500)),false
                FROM generate_series(1,20000) i""")
            await c.execute("""INSERT INTO surveillance_jobs(id,kind,venue,payload,due_at) VALUES
                ('future','wide','polymarket','{}',now()+interval '1 hour'),
                ('deep','detect','polymarket','{}',now()-interval '1 hour'),
                ('wide','wide','polymarket','{}',now()-interval '1 minute')""")
            await c.execute('ANALYZE surveillance_jobs')
            plan=await (await c.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+CLAIM_SQL,('plan-token',))).fetchone()
            self.assertIn('surveillance_jobs_ready',str(plan))
            self.assertNotIn("'Node Type': 'Seq Scan'",str(plan))
        leased=await self.store.fetch("SELECT id FROM surveillance_jobs WHERE lease_token='plan-token'")
        self.assertEqual([r['id'] for r in leased],['wide'])
        self.assertEqual((await self.store.claim())['id'],'deep')
        self.assertIsNone(await self.store.claim())

    async def test_scheduler_does_not_rewrite_unchanged_disabled_jobs_or_manual_jobs(self):
        async with self.store.connection() as c:
            await c.execute("""INSERT INTO surveillance_jobs(id,kind,venue,payload,enabled) VALUES
                ('old','trades','polymarket','{}',false),
                ('leave','detect','polymarket','{}',true),
                ('manual','details','polymarket','{"manual":true}',true)""")
        before={r['id']:r for r in await self.store.fetch('SELECT id,xmin::text AS version,due_at,enabled FROM surveillance_jobs')}
        worker=Worker(self.settings)
        try:
            await worker.schedule('polymarket')
            first={r['id']:r for r in await self.store.fetch('SELECT id,xmin::text AS version,due_at,enabled FROM surveillance_jobs')}
            await worker.schedule('polymarket')
            second={r['id']:r for r in await self.store.fetch('SELECT id,xmin::text AS version,due_at,enabled FROM surveillance_jobs')}
        finally:await worker.collector.close()
        self.assertEqual(first['old'],before['old'])
        self.assertEqual(first['manual'],before['manual'])
        self.assertFalse(first['leave']['enabled'])
        self.assertEqual(first,second)

    async def test_observation_head_and_intervals_preserve_knowledge_and_integrity(self):
        t=datetime.now(timezone.utc).replace(second=0,microsecond=0)
        async with self.store.connection() as c:
            await c.execute("""INSERT INTO surveillance_observations
                SELECT 'other:'||i,'kalshi','other',%s,%s,%s,'{}',true FROM generate_series(1,10000) i""",(t-timedelta(hours=2),t,t))
            rows=[('global',None,t-timedelta(minutes=20),t-timedelta(minutes=5),t,True),
                  ('local','c1',t-timedelta(minutes=6),t-timedelta(minutes=1),t,True),
                  ('future','c1',t-timedelta(minutes=1),t+timedelta(minutes=9),t+timedelta(minutes=2),True),
                  ('incomplete','c1',t-timedelta(minutes=1),t+timedelta(minutes=10),t,False)]
            for key,market,lo,hi,known,complete in rows:
                await c.execute("INSERT INTO surveillance_observations VALUES(%s,'kalshi',%s,%s,%s,%s,'{}',%s)",(key,market,lo,hi,known,complete))
            await c.execute('ANALYZE surveillance_observations')
        queries=[]
        original=self.store.fetch
        async def capture(sql,params=()):
            queries.append((sql,params));return await original(sql,params)
        with patch.object(self.store,'fetch',capture):
            self.assertEqual(await latest_cutoff(self.store,'kalshi',t,'c1'),t-timedelta(minutes=1))
            merged,refs=await intervals(self.store,'kalshi','c1',t-timedelta(minutes=30),t,t)
        self.assertEqual(merged,[(t-timedelta(minutes=20),t-timedelta(minutes=1))])
        self.assertEqual(set(refs),{'global','local'})
        self.assertEqual(await latest_cutoff(self.store,'kalshi',t),t-timedelta(minutes=5))
        self.assertEqual(await latest_cutoff(self.store,'polymarket',t,'unknown'),t)
        for query,params in queries:
            plan=await self.store.fetch('EXPLAIN (FORMAT JSON) '+query,params)
            self.assertIn('surveillance_observation_head',str(plan))
            self.assertNotIn("'Node Type': 'Seq Scan'",str(plan))

    async def test_noop_capacity_pass_measures_free_space_once(self):
        async with self.store.connection() as c:
            await c.execute("INSERT INTO surveillance_capacity(id,document) VALUES(1,%s)",(Jsonb(dict(reusable_database_bytes=1)),))
        with patch('surveillance.capacity.free_space',wraps=free_space) as measured:
            result=await enforce(self.store,self.settings)
        self.assertIsNone(result['error'])
        self.assertEqual(result['evicted_receipts'],0)
        self.assertEqual(measured.await_count,1)
