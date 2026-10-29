"""Integration checks for knowledge clocks, boundary windows and bounded enrichment."""
from datetime import datetime,timedelta,timezone
import os
import unittest
from unittest.mock import patch

import httpx
from psycopg.types.json import Jsonb

from surveillance.tests import test_postgres as pg
from surveillance.tests.test_core import poly,kalshi
from surveillance.normalization import now,trade,market
from surveillance.aggregates import materialize,read_bins,record_walk
from surveillance.event_review import build_review
from surveillance.wallets import admit_profile,collect_profile,self_baseline
from surveillance.api import create_app
from surveillance.worker import Worker
from surveillance.collectors import Collector


@unittest.skipUnless(os.getenv('SURVEILLANCE_TEST_DATABASE_URL'),'PostgreSQL test DSN required')
class ReviewTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=pg.PostgresTests.asyncSetUp
    asyncTearDown=pg.PostgresTests.asyncTearDown
    job=pg.PostgresTests.job

    async def add_trades(self, times, venue='polymarket', market_id='c1', offset=0, block=False):
        job=await self.job('intake'+str(offset),venue=venue)
        raw=self.archive.write(venue,'test',{},200,str(offset).encode())
        rows=[]
        for i,time in enumerate(times):
            row=dict(poly(),timestamp=int(time.timestamp()),size=10,price=.5,condition_id=market_id)
            if venue=='kalshi':
                row=kalshi(trade_id=str(i+offset),ticker=market_id,created_time=time.isoformat(),is_block_trade=block)
            rows.append(dict(trade(venue,row,raw['received_at']),id=str(i+offset)))
        await self.store.commit_page(job,raw,{},trades=rows)
        await self.store.release(job,3600)
        return raw,rows

    async def info(self,anchor,market_id='c1',venue='polymarket',verified=True,key='notice'):
        raw=self.archive.write(venue,'manual',{},0,key.encode())
        async with self.store.connection() as c:
            await self.store.insert_raw(c,raw)
            doc=dict(published_at=anchor.isoformat(),publication_time_verified=verified,title='official announcement')
            await c.execute('INSERT INTO surveillance_information(id,venue,market_id,document,raw_id) VALUES(%s,%s,%s,%s,%s)',
                (key,venue,market_id,Jsonb(doc),raw['id']))
        return key

    async def test_aggregate_versions_exclude_late_knowledge_and_skip_duplicates(self):
        end=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)-timedelta(hours=1)
        await self.add_trades([end-timedelta(seconds=30)])
        first=await materialize(self.store)
        self.assertEqual(first['appended_versions'],1)
        old=(await read_bins(self.store,'polymarket','c1',end-timedelta(hours=1),end,first['known_at']))[0]
        self.assertEqual(old['document']['fills'],1)
        await self.add_trades([end-timedelta(seconds=10)],offset=10)
        second=await materialize(self.store)
        self.assertEqual(second['appended_versions'],1)
        before=await read_bins(self.store,'polymarket','c1',end-timedelta(hours=1),end,first['known_at'])
        after=await read_bins(self.store,'polymarket','c1',end-timedelta(hours=1),end,second['known_at'])
        self.assertEqual(before[0]['document']['fills'],1)
        self.assertEqual(after[0]['document']['fills'],2)
        # A replayed page re-dirties the bucket but creates no redundant version.
        async with self.store.connection() as c:
            await c.execute('INSERT INTO surveillance_dirty_bins SELECT venue,market_id,outcome,bin_end FROM surveillance_aggregates LIMIT 1')
        self.assertEqual((await materialize(self.store))['appended_versions'],0)

    async def test_review_exact_boundary_excludes_post_disclosure_trades(self):
        anchor=datetime.now(timezone.utc).replace(minute=0,second=37,microsecond=123456)-timedelta(hours=1)
        await self.add_trades([anchor-timedelta(seconds=1),anchor+timedelta(seconds=1)])
        await materialize(self.store)
        info=await self.info(anchor)
        doc=await build_review(self.store,info,now())
        for w in doc['contracts'][0]['windows']:
            self.assertEqual(w['outcomes'][0]['fills'],1)
            self.assertEqual(w['outcomes'][0]['cash'],'5.0')
        self.assertIsNone(doc['anomaly_score'])
        self.assertEqual(len(doc['replay_raw_ids']),2)

    async def test_observed_empty_is_distinct_from_missing_and_future_information(self):
        anchor=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)-timedelta(hours=1)
        info=await self.info(anchor)
        doc=await build_review(self.store,info,now())
        self.assertEqual(doc['contracts'][0]['windows'][0]['observation'],'unknown_or_expired')
        raw=self.archive.write('polymarket','test',{},200,b'empty walk')
        j=await self.job('walk')
        await self.store.commit_page(j,raw,{},completed_walk=dict(lower_time=(anchor-timedelta(hours=1)).isoformat(),
            upper_time=anchor.isoformat(),source_upper=anchor.isoformat(),raw_ids=[raw['id']],refs_complete=True,observed_trades=0))
        doc=await build_review(self.store,info,now())
        self.assertEqual(doc['contracts'][0]['windows'][0]['observation'],'sampled_no_trades')
        self.assertEqual(doc['contracts'][0]['windows'][0]['fully_sampled_api_bins'],12)
        self.assertEqual(doc['contracts'][0]['windows'][1]['observation'],'unknown_or_expired')
        with self.assertRaisesRegex(ValueError,'unavailable'):
            await build_review(self.store,info,anchor.isoformat())

    async def test_native_event_groups_siblings_but_does_not_combine_outcomes(self):
        anchor=datetime.now(timezone.utc)-timedelta(hours=1)
        j=await self.job('catalog')
        raw=self.archive.write('polymarket','test',{},200,b'catalog')
        markets=[market('polymarket',dict(id='m'+str(i),conditionId='c'+str(i),events=[{'id':'E'}]),raw['received_at']) for i in (1,2)]
        await self.store.commit_page(j,raw,{},markets=markets,detailed=False)
        await self.info(anchor,key='a')
        await self.info(anchor,market_id='c2',key='b')
        one=await build_review(self.store,'a',now())
        await self.store.review(one['id'],'reviewed','keep review','analyst')
        two=await build_review(self.store,'b',now())
        self.assertEqual(one['id'],two['id'])
        self.assertEqual(two['status'],'reviewed')
        self.assertEqual(two['known_members'],['c1','c2'])
        self.assertEqual(len(two['contracts']),2)
        self.assertEqual(len(await self.store.fetch('SELECT * FROM surveillance_cases')),1)
        self.assertEqual(len(await self.store.fetch('SELECT * FROM surveillance_case_versions')),3)

    async def test_verified_intake_queues_review_and_api_validates_input(self):
        from dataclasses import replace
        app=create_app(replace(self.settings,api_token='test-token'))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':'Bearer test-token'}) as client:
            info=dict(venue='polymarket',market_id='c1',source_url='https://example.test/official',title='Notice',content='text',published_at='2026-01-01T00:00:00Z')
            self.assertEqual((await client.post('/information',json=info)).status_code,200)
            self.assertFalse(await self.store.fetch("SELECT * FROM surveillance_jobs WHERE kind='event_review'"))
            response=await client.post('/information',json=dict(info,publication_time_verified=True,verification_note='official timestamp checked'))
            self.assertEqual(response.status_code,200)
            jobs=await self.store.fetch("SELECT * FROM surveillance_jobs WHERE kind='event_review'")
            self.assertEqual(len(jobs),1)
            worker=Worker(self.settings)
            await worker.run_once()
            await worker.collector.close()
            self.assertFalse((await self.store.fetch('SELECT enabled FROM surveillance_jobs'))[0]['enabled'])
            self.assertEqual(len(await self.store.fetch('SELECT * FROM surveillance_cases')),1)
            invalid=await client.get('/aggregates',params=dict(venue='kalshi',market_id='c1',start='2026-01-01',end=now(),as_of=now()))
            self.assertEqual(invalid.status_code,422)

    async def test_wallet_budget_truncation_and_score_preservation(self):
        cutoff=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        wallet='0x'+'a'*40
        case=dict(id='alert',venue='polymarket',market_id='c1',anomaly_score=70,evidence_quality=50,
            investigation_priority=45,status='candidate',signal=dict(as_of=cutoff,window_seconds=3600),
            wallet_observations=[dict(wallet=wallet,cash_usd=50)])
        await self.store.save_case(case)
        for i in range(4):
            self.assertIsNotNone(await admit_profile(self.store,dict(case,id='alert'+str(i))))
        self.assertIsNone(await admit_profile(self.store,dict(case,id='over-budget')))
        self.assertIsNone(await admit_profile(self.store,dict(case,venue='kalshi')))
        # Use a fresh admission budget in this isolated schema.
        async with self.store.connection() as c:
            await c.execute('DELETE FROM surveillance_jobs')
            await c.execute('DELETE FROM surveillance_wallet_profiles')
        await admit_profile(self.store,case)
        def handler(request):
            self.assertEqual(request.url.params['user'],wallet)
            self.assertEqual(request.url.params['limit'],'500')
            self.assertEqual(request.url.params['taker_only'],'false')
            cursor='one' if not request.url.params.get('cursor') else 'two'
            row=dict(poly(),proxy_wallet=wallet,timestamp=int(datetime.fromisoformat(cutoff).timestamp())-10,size=10,price=.5)
            return httpx.Response(200,json={'data':[row],'pagination':{'has_more':True,'next_cursor':cursor}})
        worker=Worker(self.settings,Collector(self.store,self.archive,0,httpx.AsyncClient(transport=httpx.MockTransport(handler))))
        for _ in range(2):
            job=await self.store.claim()
            await collect_profile(worker,job)
            await self.store.release(job,0)
        await worker.collector.close()
        profile=(await self.store.fetch('SELECT document FROM surveillance_wallet_profiles'))[0]['document']
        self.assertEqual(profile['status'],'truncated')
        self.assertIsNone(profile['summary']['current_to_own_p95'])
        enriched=(await self.store.fetch('SELECT document FROM surveillance_cases'))[0]['document']
        self.assertEqual(enriched['anomaly_score'],70)
        self.assertEqual(enriched['investigation_priority'],45)
        self.assertEqual(len(enriched['wallet_profiles']),1)
        self.assertEqual(len(await self.store.fetch('SELECT * FROM surveillance_case_versions')),2)

    async def test_fifo_and_retention_include_derived_source_references(self):
        from surveillance.capacity import evict_batch
        from surveillance.maintenance import prune,reset_test_dataset
        time=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)-timedelta(hours=1)
        raw,_=await self.add_trades([time])
        await materialize(self.store)
        async with self.store.connection() as c:
            await c.execute("UPDATE surveillance_raw SET received_at=now()-interval '10 days'")
            await c.execute('DELETE FROM surveillance_trades')
        self.assertEqual((await prune(self.store))['expired_raw_receipts'],0)
        async with self.store.connection() as c:
            self.assertEqual(await evict_batch(c,1),1)
        self.assertFalse(await self.store.fetch('SELECT * FROM surveillance_aggregates'))
        await reset_test_dataset(self.store,self.folder.name)
        self.assertFalse(await self.store.fetch('SELECT * FROM surveillance_dirty_bins'))

    async def test_unverified_information_and_large_families_require_explicit_scope(self):
        anchor=datetime.now(timezone.utc)-timedelta(hours=1)
        await self.info(anchor,verified=False,key='unverified')
        with self.assertRaisesRegex(ValueError,'Verified'):
            await build_review(self.store,'unverified',now())
        await self.info(anchor)
        j=await self.job('family')
        raw=self.archive.write('polymarket','test',{},200,b'large family')
        markets=[market('polymarket',dict(id='m'+str(i),conditionId='c'+str(i),events=[{'id':'E'}]),raw['received_at']) for i in range(21)]
        await self.store.commit_page(j,raw,{},markets=markets,detailed=False)
        with self.assertRaisesRegex(ValueError,'exceeds 20'):
            await build_review(self.store,'notice',now())
        result=await build_review(self.store,'notice',now(),contract_only=True)
        self.assertEqual(result['known_members'],['c1'])

    async def test_missing_aggregate_never_becomes_an_empty_observation(self):
        anchor=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)-timedelta(hours=1)
        await self.add_trades([anchor-timedelta(minutes=10)])
        await self.info(anchor)
        # No materialization yet; raw source fills still exist.
        doc=await build_review(self.store,'notice',now())
        self.assertEqual(doc['contracts'][0]['windows'][0]['observation'],'pending_aggregation')
        self.assertFalse(doc['contracts'][0]['windows'][0]['outcomes'])

    async def test_historical_aggregate_rebuild_uses_current_knowledge_time(self):
        from argparse import Namespace
        from surveillance.cli import execute
        t=datetime.now(timezone.utc)-timedelta(days=100)
        await self.add_trades([t])
        async with self.store.connection() as c:
            await c.execute('DELETE FROM surveillance_dirty_bins')
        with patch('surveillance.cli.Settings.env',return_value=self.settings):
            await execute(Namespace(command='aggregate-market',venue='polymarket',market='c1',start=(t-timedelta(hours=1)).isoformat(),end=(t+timedelta(hours=1)).isoformat()))
        await materialize(self.store)
        row=(await self.store.fetch('SELECT * FROM surveillance_aggregates'))[0]
        self.assertGreater(row['known_at'],t+timedelta(days=99))

    async def test_kalshi_blocks_excluded_from_directional_cash(self):
        t=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)-timedelta(hours=1)
        await self.add_trades([t],venue='kalshi',block=True)
        await materialize(self.store)
        doc=(await self.store.fetch('SELECT document FROM surveillance_aggregates'))[0]['document']
        self.assertGreater(float(doc['cash']),0)
        self.assertEqual(float(doc['buy_cash']),0)
        self.assertEqual(float(doc['sell_cash']),0)


class WalletStatisticsTests(unittest.TestCase):
    def test_self_baseline_requires_complete_multi_day_history(self):
        rows=[dict(price='0.5',quantity='10',event_time=f'2026-10-{20+i%2}T00:00:00+00:00',market_id='m') for i in range(20)]
        rows.append(dict(price='0.5',quantity='100',event_time='2026-10-22T00:01:00+00:00',market_id='m'))
        args=(rows,'2026-10-22T00:00:00+00:00','2026-10-22T01:00:00+00:00')
        self.assertEqual(self_baseline(*args,True)['current_to_own_p95'],10)
        self.assertIsNone(self_baseline(*args,False)['current_to_own_p95'])
        self.assertIsNone(self_baseline(rows[-1:],args[1],args[2],True)['current_to_own_p95'])
