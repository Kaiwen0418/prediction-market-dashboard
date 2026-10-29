"""Regression coverage for the observed pool failures and global intake."""
from collections import Counter
from datetime import datetime,timedelta,timezone
import os
import unittest
from dataclasses import replace

import httpx
from psycopg.types.json import Jsonb

from surveillance.discovery import Selector,select,theme,event_key
from surveillance.normalization import market,now
from surveillance.worker import Worker
from surveillance.collectors import Collector
from surveillance.tests import test_postgres as pg
from surveillance.tests.test_core import poly


class SelectionTests(unittest.TestCase):
    def m(self,i,title='Policy announcement',event=None,volume='10000',**kw):
        return dict(id=str(i),venue='kalshi',condition_id=None,closed=False,tradable=True,title=title,
                    volume=volume,event_ids=[event or str(i)],**kw)

    def test_nominal_and_election_win_do_not_become_appointments(self):
        self.assertEqual(theme(self.m(1,'Will the US effective tariff rate (nominal imports) be above 9%?')),'other')
        self.assertEqual(theme(self.m(2,'Will a Republican win the House race for WI-3?')),'civic')
        self.assertEqual(theme(self.m(3,'Who will President Trump nominate as Fed Chair?')),'information')
        self.assertEqual(theme(self.m(4,'Who will win the Nobel Peace Prize?')),'information')
        self.assertEqual(theme(self.m(5,'2026 FIDE World Senior chess tournament: Ribac wins')),'sports')
        self.assertEqual(theme(self.m(6,'A vs. B: Over 2.5 goals')),'sports')
        self.assertEqual(theme(self.m(7,'Will approval rating be above 50%?')),'other')

    def test_unmapped_rows_are_enrichment_candidates_not_independent_events(self):
        s=Selector(20)
        for i in range(100):s.add(dict(self.m(i),event_ids=[]))
        s.add(dict(self.m('ambiguous'),event_ids=['one','two']))
        self.assertEqual(s.result(),[])
        self.assertEqual(s.counts['unmapped'],101)
        self.assertLessEqual(len(s.unmapped.items),20)

    def test_numeric_encodings_do_not_duplicate_global_and_market_fills(self):
        from surveillance.normalization import trade
        one=trade('polymarket',dict(poly(),price=.6,size=10),now())
        two=trade('polymarket',dict(poly(),price='0.6000',size='10.000'),now())
        self.assertEqual(one['identity'],two['identity'])

    def test_event_crowding_cannot_consume_budget_and_low_quota_is_guaranteed(self):
        rows=[self.m(i,event='one-tariff-event') for i in range(100)]
        rows += [self.m(100+i,title='Policy announcement',event='info'+str(i)) for i in range(60)]
        rows += [self.m(200+i,title='Sports tournament',event='sport'+str(i)) for i in range(60)]
        rows += [self.m(300+i,title='House election',event='civic'+str(i)) for i in range(60)]
        rows += [self.m(400+i,title='Quiet market',volume='0',event='quiet'+str(i)) for i in range(60)]
        s=Selector(100);[s.add(m) for m in rows];chosen=s.result()
        self.assertEqual(len(chosen),100)
        self.assertLessEqual(max(Counter(event_key(m) for m in chosen).values()),2)
        self.assertEqual(sum(v['reason']=='low_activity_exploration' for v in s.selection.values()),20)
        counts=Counter(theme(m) for m in chosen)
        self.assertGreaterEqual(counts['information'],30)
        self.assertGreaterEqual(counts['sports'],25)
        self.assertGreaterEqual(counts['civic'],10)
        self.assertTrue(all(len(p.items)<=100 for p in s.pools.values()))

    def test_broad_activity_can_promote_an_unselected_low_rank_contract(self):
        rows=[self.m(i) for i in range(100)]
        outsider=self.m(100,title='Policy decision',volume='1001')
        self.assertNotIn('100',{m['id'] for m in select(rows+[outsider],20)})
        s=Selector(20,scouts={'100':{'recent_cash':20000,'prior_cash':100}},previous={m['id'] for m in rows})
        for m in rows+[outsider]:s.add(m)
        chosen=s.result()
        self.assertIn('100',{m['id'] for m in chosen})
        self.assertEqual(s.selection['100']['reason'],'wide_activity_promotion')


@unittest.skipUnless(os.getenv('SURVEILLANCE_TEST_DATABASE_URL'),'PostgreSQL test DSN required')
class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=pg.PostgresTests.asyncSetUp
    asyncTearDown=pg.PostgresTests.asyncTearDown
    job=pg.PostgresTests.job

    async def test_sparse_details_preserve_metadata_provenance_and_explicit_empty_clears(self):
        j=await self.job('detail','details')
        raw=self.archive.write('polymarket','catalog',{},200,b'catalog')
        m=market('polymarket',dict(id='m',conditionId='c1',events=[{'id':'E'}],tags=[{'label':'Sports'}],volume24hr=32,volumeNum=30000),raw['received_at'])
        await self.store.commit_page(j,raw,{},markets=[m],detailed=False)
        # Existing schema-2 rows have no field-level provenance yet.
        async with self.store.connection() as c:
            await c.execute("UPDATE surveillance_markets SET document=document-'field_sources',metadata_raw_ids='{}'")
        detail=self.archive.write('polymarket','detail',{},200,b'detail')
        m=market('polymarket',dict(id='m',conditionId='c1',description='rules'),detail['received_at'])
        await self.store.commit_page(j,detail,{},markets=[m])
        row=(await self.store.fetch('SELECT * FROM surveillance_markets'))[0]
        self.assertEqual(row['document']['event_ids'],['E'])
        self.assertEqual(row['document']['tags'],['Sports'])
        self.assertEqual(row['document']['volume'],'30000')
        self.assertTrue(row['document']['volume_reported'])
        self.assertEqual(row['document']['field_sources']['event_ids']['raw_id'],raw['id'])
        self.assertEqual(row['metadata_raw_ids'],[raw['id']])
        m=market('polymarket',dict(id='m',conditionId='c1',events=[],tags=[]),detail['received_at'])
        await self.store.commit_page(j,detail,{},markets=[m])
        row=(await self.store.fetch('SELECT * FROM surveillance_markets'))[0]
        self.assertEqual(row['document']['event_ids'],[])
        self.assertIn(detail['id'],row['metadata_raw_ids'])

    async def test_wide_restart_dedup_and_cross_market_sampling(self):
        t=int(datetime.now(timezone.utc).timestamp())-10
        a=dict(poly(),timestamp=t,condition_id='outside-a')
        b=dict(poly(),timestamp=t-1,condition_id='outside-b')
        calls=[]
        def handler(req):
            calls.append(dict(req.url.params))
            self.assertNotIn('condition',req.url.params)
            rows,nxt=([b],None) if req.url.params.get('cursor') else ([a],'next')
            return httpx.Response(200,json={'data':rows,'pagination':{'has_more':bool(nxt),'next_cursor':nxt}})
        w=Worker(self.settings,Collector(self.store,self.archive,0,httpx.AsyncClient(transport=httpx.MockTransport(handler))))
        await self.store.enqueue('wide','wide','polymarket',{'scope':'global'})
        j=await self.store.claim();await w.ingest(j);await self.store.release(j,0)
        j=await self.store.claim();await w.ingest(j);await self.store.release(j,0)
        self.assertEqual({r['market_id'] for r in await self.store.fetch('SELECT * FROM surveillance_trades')},{'outside-a','outside-b'})
        self.assertFalse(await self.store.fetch('SELECT * FROM surveillance_walks'))
        # Restart/repeat the global walk: counters count fills once across paths.
        j=await self.store.claim();await w.ingest(j);await self.store.release(j,0)
        j=await self.store.claim();await w.ingest(j)
        self.assertEqual(sum(r['fills'] for r in await self.store.fetch('SELECT * FROM surveillance_scout')),2)
        self.assertEqual(len(await self.store.fetch('SELECT * FROM surveillance_trades')),2)
        self.assertEqual(calls[1]['cursor'],'next')
        await w.collector.close()

    async def test_metadata_raw_pins_survive_retention_and_capacity_expires_dependents(self):
        from surveillance.maintenance import prune
        from surveillance.capacity import evict_batch
        old=(datetime.now(timezone.utc)-timedelta(days=10)).isoformat()
        j=await self.job('detail','details')
        raw=self.archive.write('polymarket','catalog',{},200,b'old metadata',old)
        m=market('polymarket',dict(id='m',conditionId='c1',events=[{'id':'E'}]),old)
        await self.store.commit_page(j,raw,{},markets=[m],detailed=False)
        detail=self.archive.write('polymarket','detail',{},200,b'new detail')
        m=market('polymarket',dict(id='m',conditionId='c1'),detail['received_at'])
        await self.store.commit_page(j,detail,{},markets=[m])
        self.assertEqual((await prune(self.store))['expired_raw_receipts'],0)
        async with self.store.connection() as c:await evict_batch(c,1)
        self.assertFalse(await self.store.fetch('SELECT * FROM surveillance_markets'))

    async def test_filtered_gamma_detail_recovers_event_and_rejects_wrong_id(self):
        from surveillance.collectors import ContractError
        def handler(req):
            self.assertEqual(req.url.params['id'],'m')
            return httpx.Response(200,json=[dict(id='m',conditionId='c',events=[{'id':'E'}],tags=[{'label':'Sports'}])])
        w=Worker(self.settings,Collector(self.store,self.archive,0,httpx.AsyncClient(transport=httpx.MockTransport(handler))))
        j=await self.job('detail','details');j['payload']={'catalog_id':'m','market_id':'c'}
        await w.ingest(j)
        row=(await self.store.fetch('SELECT document FROM surveillance_markets'))[0]['document']
        self.assertEqual(row['event_ids'],['E'])
        await w.collector.close()

    async def test_unknown_broad_market_queues_condition_lookup_then_enters_selection(self):
        condition='0x'+'a'*64
        def handler(req):
            self.assertEqual(req.url.params['condition_ids'],condition)
            return httpx.Response(200,json=[dict(id='new-market',conditionId=condition,
                events=[{'id':'native-event'}],question='Policy decision',active=True,acceptingOrders=True)])
        w=Worker(self.settings,Collector(self.store,self.archive,0,httpx.AsyncClient(transport=httpx.MockTransport(handler))))
        await w.resolve_unknowns('polymarket',[dict(market_id=condition,quantity='10000',price='.5')])
        jobs=await self.store.fetch('SELECT payload FROM surveillance_jobs')
        self.assertTrue(jobs[0]['payload']['lookup'])
        await w.run_once()
        row=(await self.store.fetch('SELECT document FROM surveillance_markets'))[0]['document']
        self.assertEqual(row['event_ids'],['native-event'])
        await w.schedule('polymarket')
        selected=await self.store.fetch("SELECT payload FROM surveillance_jobs WHERE enabled AND kind='trades'")
        self.assertEqual(selected[0]['payload']['market_id'],condition)
        await w.collector.close()

    async def test_kalshi_global_uses_pinned_time_without_ticker_and_reports_pending(self):
        from surveillance.tests.test_core import kalshi
        def handler(req):
            self.assertNotIn('ticker',req.url.params)
            self.assertIn('min_ts',req.url.params)
            self.assertTrue(req.url.path.endswith('/markets/trades'))
            return httpx.Response(200,json={'trades':[kalshi(created_time=(datetime.now(timezone.utc)-timedelta(seconds=10)).isoformat())],'cursor':'pending'})
        w=Worker(self.settings,Collector(self.store,self.archive,0,httpx.AsyncClient(transport=httpx.MockTransport(handler))))
        await self.store.enqueue('wide','wide','kalshi',{'scope':'global'})
        j=await self.store.claim();await w.ingest(j)
        cp=(await self.store.fetch('SELECT checkpoint FROM surveillance_jobs'))[0]['checkpoint']
        self.assertEqual(cp['cursor'],'pending')
        self.assertNotIn('completed_at',cp)
        record=(await self.store.fetch("SELECT document FROM surveillance_coverage WHERE kind='walk_pending'"))[0]['document']
        self.assertEqual(record['scope'],'global')
        self.assertFalse(await self.store.fetch('SELECT * FROM surveillance_walks'))
        await w.collector.close()

    async def test_cached_global_feed_is_observable_and_not_claimed_fresh(self):
        from surveillance.api import create_app
        timestamp=int((datetime.now(timezone.utc)-timedelta(seconds=180)).timestamp())
        def handler(req):
            return httpx.Response(200,headers={'cache-control':'public, max-age=300','age':'123'},
                json={'data':[dict(poly(),timestamp=timestamp)],'pagination':{'has_more':False,'next_cursor':None}})
        w=Worker(self.settings,Collector(self.store,self.archive,0,httpx.AsyncClient(transport=httpx.MockTransport(handler))))
        await self.store.enqueue('wide','wide','polymarket',{'scope':'global'})
        j=await self.store.claim();await w.ingest(j)
        app=create_app(replace(self.settings,api_token='test'))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':'Bearer test'}) as client:
            r=await client.get('/coverage');quality=r.json()['wide_freshness'][0]
            self.assertEqual(quality['observation'],'stale_head_observation')
            self.assertEqual(quality['http_cache_control'],'public, max-age=300')
            self.assertEqual(quality['http_age'],'123')
        raw=(await self.store.fetch('SELECT * FROM surveillance_raw'))[0]
        self.assertEqual(raw['response_headers']['age'],'123')
        await w.collector.close()
