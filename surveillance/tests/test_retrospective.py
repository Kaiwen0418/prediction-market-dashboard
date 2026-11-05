from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
import unittest

import httpx
from psycopg.types.json import Jsonb

from surveillance.leadlag import analyze, iso
from surveillance.normalization import market, now
from surveillance.research_archive import read_tape, maintain
from surveillance.retrospective import register, run, discover, dispatch
from surveillance.worker import Worker
from surveillance.collectors import Collector
from surveillance.tests import test_postgres as pg
from surveillance.tests.test_core import poly
from surveillance.api import create_app


def tape():
    base=datetime(2026,1,1,tzinfo=timezone.utc).timestamp()
    result=[]
    for i in range(20):
        for j in range(3):
            result.append(dict(id=f'{i}:{j}',event_time=iso(base+i*300+j),received_at=iso(base+10000),
                outcome='yes',token_id='yes',price=str(.2 if i<12 else .45),quantity='100',
                direction=1,wallet='early' if i in (9,10) else 'others',cash_price='.2',
                cash_notional='20',venue='polymarket',market_id='c1'))
    return result,iso(base),iso(base+20*300)


class LeadTests(unittest.TestCase):
    def test_precursor_is_before_onset_not_threshold_and_no_payout_needed(self):
        rows,start,end=tape();r=analyze(rows,start,end)
        self.assertEqual(len(r['episodes']),1)
        e=r['episodes'][0];w=next(w for w in e['wallets'] if w['wallet']=='early')
        self.assertGreater(w['lead_seconds_min'],0)
        self.assertEqual(w['action'],'buy_before_rise')
        self.assertFalse(w['own_impact_unresolved'])
        self.assertEqual(r['analysis_mode'],'retrospective')
        self.assertIsNone(r['anomaly_score'])

    def test_gap_reversal_and_outcome_mixing_do_not_create_signal(self):
        rows,start,end=tape()
        rows=[r for r in rows if not r['id'].startswith('11:')]
        self.assertEqual(analyze(rows,start,end)['episodes'],[])
        rows,start,end=tape()
        for t in rows:
            if int(t['id'].split(':')[0])>=13:t['price']='.2'
        self.assertEqual(analyze(rows,start,end)['episodes'],[])
        rows,start,end=tape()
        for t in rows:
            if int(t['id'].split(':')[0])>=12:t['token_id']='no'
        self.assertEqual(analyze(rows,start,end)['episodes'],[])

    def test_sell_before_decline_and_self_impact_are_explicit(self):
        rows,start,end=tape()
        for t in rows:
            t['price']=str(1-float(t['price']));t['direction']=-1
            if int(t['id'].split(':')[0])>=12:t['wallet']='early'
        r=analyze(rows,start,end)
        w=next(x for x in r['episodes'][0]['wallets'] if x['wallet']=='early')
        self.assertEqual(w['action'],'sell_before_fall')
        self.assertTrue(w['own_impact_unresolved'])


@unittest.skipUnless(os.getenv('SURVEILLANCE_TEST_DATABASE_URL'),'Postgres required')
class RetrospectiveTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=pg.PostgresTests.asyncSetUp
    asyncTearDown=pg.PostgresTests.asyncTearDown

    async def final_market(self):
        end=datetime.now(timezone.utc)-timedelta(hours=1)
        row=dict(id='m1',conditionId='c1',question='Unclassified event',outcomes=['yes','no'],
            clobTokenIds=['yes','no'],closed=True,umaResolutionStatus='resolved',outcomePrices=['1','0'],
            createdAt=(end-timedelta(days=2)).isoformat(),endDate=end.isoformat(),events=[{'id':'e1'}])
        raw=self.archive.write('polymarket','catalog',{},200,b'{}')
        await self.store.raw(raw)
        return market('polymarket',row,raw['received_at']),raw,row

    async def test_finality_idempotence_revision_and_no_category_filter(self):
        m,raw,row=await self.final_market()
        async with self.store.connection() as c:
            first=await register(c,m,raw,self.settings)
            self.assertEqual(await register(c,m,raw,self.settings),first)
            closed=market('polymarket',dict(row,umaResolutionStatus='proposed'),now())
            self.assertIsNone(await register(c,closed,raw,self.settings))
            raw2=dict(raw,received_at=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat())
            again=await register(c,m,raw2,self.settings)
            self.assertNotEqual(first,again)
        states=await self.store.fetch('SELECT status FROM surveillance_retrospectives WHERE id=%s',(first,))
        self.assertEqual(states[0]['status'],'superseded')

    async def test_atomic_archive_dedup_hot_fifo_and_replay(self):
        from surveillance.capacity import evict_batch
        rows,start,end=tape();raw=self.archive.write('polymarket','trades',{},200,b'{"tape":1}')
        await self.store.enqueue('test','trades','polymarket',{'market_id':'c1'})
        job=await self.store.claim()
        await self.store.commit_page(job,raw,{},trades=rows)
        await self.store.commit_page(job,raw,{},trades=rows)
        archived,refs=await read_tape(self.store,'polymarket','c1',start,end)
        self.assertEqual(len(archived),len(rows))
        async with self.store.connection(exclusive=True) as c:await evict_batch(c,100)
        archived,refs=await read_tape(self.store,'polymarket','c1',start,end)
        self.assertEqual(len(archived),len(rows))
        self.assertEqual(await self.store.fetch('SELECT id FROM surveillance_trades'),[])
        self.assertEqual(len(analyze(archived,start,end)['episodes']),1)
        measured=await self.store.fetch('SELECT logical_bytes FROM surveillance_research_budget WHERE name=%s',('surveillance_research_tape',))
        self.assertGreater(measured[0]['logical_bytes'],0)
        await maintain(self.store,replace(self.settings,research_tape_max_bytes=1))
        self.assertEqual((await read_tape(self.store,'polymarket','c1',start,end))[0],[])
        self.assertEqual((await self.store.fetch('SELECT logical_bytes FROM surveillance_research_budget WHERE name=%s',('surveillance_research_tape',)))[0]['logical_bytes'],0)

    async def test_mode_stops_automatic_online_work_but_keeps_manual(self):
        for key,kind,payload in [('deep','trades',{}),('scan','candidate_scan',{}),('manual','details',{'manual':True}),('auto','details',{'manual':True,'lookup':True})]:
            await self.store.enqueue(key,kind,'polymarket',payload)
        worker=Worker(replace(self.settings,mode='retrospective'))
        try:await worker.seed()
        finally:await worker.collector.close()
        active={r['id'] for r in await self.store.fetch('SELECT id FROM surveillance_jobs WHERE enabled')}
        self.assertIn('manual',active);self.assertNotIn('deep',active);self.assertNotIn('auto',active)
        self.assertNotIn('wide:polymarket:v2',active);self.assertIn('retrospective-dispatch',active)

    async def test_discovery_resume_and_sliced_report_api(self):
        m,raw,row=await self.final_market();calls=[]
        def handler(request):
            calls.append(dict(request.url.params))
            return httpx.Response(200,json={'markets':[row],'next_cursor':None})
        settings=replace(self.settings,mode='retrospective',review_max_pages=1)
        worker=Worker(settings,Collector(self.store,self.archive,0,httpx.AsyncClient(transport=httpx.MockTransport(handler))))
        try:
            await self.store.enqueue('settlements','settlement_discovery','polymarket',{})
            job=await self.store.claim();await discover(worker,job);await self.store.release(job,3600)
            reviews=await self.store.fetch('SELECT * FROM surveillance_retrospectives')
            self.assertEqual(len(reviews),1)
            self.assertEqual((await self.store.fetch('SELECT count(*) AS n FROM surveillance_markets'))[0]['n'],1)
            await self.store.enqueue('dispatch','retrospective_dispatch','system',{})
            job=await self.store.claim();await dispatch(worker,job);await self.store.release(job,3600)
            job=await self.store.claim()
            self.assertEqual(job['kind'],'retrospective')
            # Simulate a completed but empty bounded HTTP walk, then restart.
            cp=dict(continuity_version=1,stage='analyze',next_end=reviews[0]['document']['requested_end'],backfill_status='page_budget_exhausted')
            await self.store.checkpoint(job,cp);job['checkpoint']=cp
            await run(worker,job)
            saved=(await self.store.fetch('SELECT checkpoint FROM surveillance_jobs WHERE id=%s',(job['id'],)))[0]['checkpoint']
            self.assertEqual(saved['slices'],1)
            self.assertEqual(saved['incomplete_slices'],0)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(replace(settings,api_token='test'))),base_url='http://test',headers={'Authorization':'Bearer test'}) as client:
                response=await client.get('/retrospectives/'+reviews[0]['id'])
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['slices'][0]['document']['input_status'],'no_observed_inputs')
        finally:await worker.collector.close()

    async def test_bounded_backfill_resumes_and_records_actual_receipt_time(self):
        from surveillance.retrospective import collect_page
        m,raw,row=await self.final_market()
        async with self.store.connection() as c:key=await register(c,m,raw,self.settings)
        review=(await self.store.fetch('SELECT * FROM surveillance_retrospectives WHERE id=%s',(key,)))[0]
        when=datetime.fromisoformat(review['document']['requested_end'])-timedelta(minutes=10)
        source=dict(poly(),timestamp=int(when.timestamp()))
        calls=[]
        def handler(request):
            calls.append(dict(request.url.params))
            cursor=request.url.params.get('cursor')
            return httpx.Response(200,json={'data':[source], 'pagination':{'has_more':cursor is None,'next_cursor':'next' if cursor is None else None}})
        worker=Worker(replace(self.settings,mode='retrospective'),Collector(self.store,self.archive,0,httpx.AsyncClient(transport=httpx.MockTransport(handler))))
        try:
            await self.store.enqueue('r','retrospective','polymarket',{'review_id':key,'market_id':'c1'})
            job=await self.store.claim()
            await collect_page(worker,job,review,{'stage':'collect'})
            job['checkpoint']=(await self.store.fetch('SELECT checkpoint FROM surveillance_jobs WHERE id=%s',(job['id'],)))[0]['checkpoint']
            await collect_page(worker,job,review,dict(job['checkpoint']))
            cp=(await self.store.fetch('SELECT checkpoint FROM surveillance_jobs WHERE id=%s',(job['id'],)))[0]['checkpoint']
            self.assertEqual(cp['phase'],1)
            self.assertEqual(calls[1]['cursor'],'next')
            await collect_page(worker,job,review,cp)
            rows,_=await read_tape(self.store,'polymarket','c1',review['document']['requested_start'],review['document']['requested_end'])
            self.assertEqual(len(rows),2)  # identical public fills retain scan multiplicity
            self.assertTrue(all(t['received_at']>t['event_time'] for t in rows))
            self.assertEqual((await self.store.fetch('SELECT checkpoint FROM surveillance_jobs WHERE id=%s',(job['id'],)))[0]['checkpoint']['pass'],2)
        finally:await worker.collector.close()

    async def test_kalshi_reads_both_public_tapes_and_deduplicates_overlap(self):
        from surveillance.retrospective import collect_page
        from surveillance.tests.test_core import kalshi
        m,raw,row=await self.final_market()
        start=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat();end=now()
        review={'document':{'requested_start':start,'requested_end':end}}
        source=kalshi();source.update(ticker='k1',created_time=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())
        urls=[]
        def handler(request):
            urls.append(request.url.path)
            self.assertIn('min_ts',request.url.params);self.assertIn('max_ts',request.url.params)
            return httpx.Response(200,json={'trades':[source],'cursor':''})
        worker=Worker(replace(self.settings,mode='retrospective'),Collector(self.store,self.archive,0,httpx.AsyncClient(transport=httpx.MockTransport(handler))))
        try:
            async with self.store.connection() as c:
                await c.execute("INSERT INTO surveillance_retrospectives(id,venue,market_id,status,document) VALUES('kr','kalshi','k1','collecting','{}')")
            await self.store.enqueue('k','retrospective','kalshi',{'market_id':'k1','review_id':'kr'})
            job=await self.store.claim();cp={}
            for _ in range(3):
                await collect_page(worker,job,review,cp)
                cp=(await self.store.fetch('SELECT checkpoint FROM surveillance_jobs WHERE id=%s',(job['id'],)))[0]['checkpoint']
            rows,_=await read_tape(self.store,'kalshi','k1',start,end)
            self.assertEqual(len(rows),1)
            self.assertEqual(urls,['/trade-api/v2/markets/trades','/trade-api/v2/historical/trades'])
            self.assertEqual(cp['stage'],'collect')
            self.assertEqual(cp['pass'],2)
        finally:await worker.collector.close()

    async def test_archive_eviction_retracts_sampled_coverage(self):
        from surveillance.research_archive import capture_walk,coverage
        rows,start,end=tape();raw=self.archive.write('polymarket','trades',{},200,b'{}')
        await self.store.enqueue('r','trades','polymarket',{'market_id':'c1'})
        job=await self.store.claim();await self.store.commit_page(job,raw,{},trades=rows)
        async with self.store.connection() as c:await capture_walk(c,job,dict(lower_time=start,source_upper=end,raw_ids=[raw['id']],refs_complete=True))
        self.assertEqual((await coverage(self.store,'polymarket','c1',start,end))['sampled_fraction'],1)
        await maintain(self.store,replace(self.settings,research_tape_max_bytes=1))
        self.assertEqual((await coverage(self.store,'polymarket','c1',start,end))['sampled_fraction'],0)

    async def test_replay_cutoff_excludes_later_archived_fills(self):
        from surveillance.research_archive import capture
        rows,start,end=tape();raw=self.archive.write('polymarket','trades',{},200,b'{}')
        async with self.store.connection() as c:await capture(c,rows,raw)
        cutoff=now()
        raw2=self.archive.write('polymarket','trades',{},200,b'{"late":true}')
        async with self.store.connection() as c:await capture(c,[dict(rows[0],id='late-fill')],raw2)
        before,_=await read_tape(self.store,'polymarket','c1',start,end,known_at=cutoff)
        after,_=await read_tape(self.store,'polymarket','c1',start,end)
        self.assertEqual(len(before),len(rows))
        self.assertEqual(len(after),len(rows)+1)
        self.assertNotEqual(analyze(before,start,end)['input_digest'],analyze(after,start,end)['input_digest'])

    async def test_full_interval_requires_two_walks_and_protects_evidence(self):
        from surveillance.retrospective import collect_page
        from surveillance.capacity import evict_batch
        from surveillance.research_archive import maintain
        m,raw,row=await self.final_market()
        async with self.store.connection() as c:key=await register(c,m,raw,self.settings)
        review=(await self.store.fetch('SELECT * FROM surveillance_retrospectives WHERE id=%s',(key,)))[0]
        when=datetime.fromisoformat(review['document']['requested_end'])-timedelta(minutes=10)
        source=dict(poly(),timestamp=int(when.timestamp()))
        def handler(request):
            return httpx.Response(200,json={'data':[source],'pagination':{'has_more':not bool(request.url.params.get('cursor')),'next_cursor':'next' if not request.url.params.get('cursor') else None}})
        worker=Worker(replace(self.settings,review_max_pages=1),Collector(self.store,self.archive,0,httpx.AsyncClient(transport=httpx.MockTransport(handler))))
        try:
            await self.store.enqueue('continuous','retrospective','polymarket',{'review_id':key,'market_id':'c1'})
            job=await self.store.claim();cp={}
            for _ in range(6):
                await collect_page(worker,job,review,cp)
                cp=(await self.store.fetch('SELECT checkpoint FROM surveillance_jobs WHERE id=%s',(job['id'],)))[0]['checkpoint']
            self.assertEqual(cp['continuity_status'],'verified_api_interval')
            self.assertEqual(cp['stage'],'analyze')
            self.assertEqual(len(await self.store.fetch('SELECT * FROM surveillance_review_pages')),4)
            async with self.store.connection(exclusive=True) as c:await evict_batch(c,100)
            await maintain(self.store,replace(self.settings,research_tape_max_bytes=1))
            self.assertEqual(len(await self.store.fetch('SELECT * FROM surveillance_review_pages')),4)
            self.assertGreater(len(await self.store.fetch('SELECT id FROM surveillance_research_tape')),0)
        finally:await worker.collector.close()

    async def test_empty_verified_reports_release_admission_slots(self):
        async with self.store.connection() as c:
            await c.execute('''INSERT INTO surveillance_retrospectives(id,venue,market_id,status,document)
                SELECT 'empty'||i,'polymarket','c'||i,'complete_observed',
                '{"continuity_required":true,"continuity":{"fills_per_walk":0},"market":{"volume":"0"}}'
                FROM generate_series(1,20) i''')
            await c.execute('''INSERT INTO surveillance_retrospectives(id,venue,market_id,status,document)
                VALUES('positive','kalshi','k','pending','{"market":{"volume":"100"}}')''')
        await self.store.enqueue('dispatch','retrospective_dispatch','system',{})
        worker=Worker(replace(self.settings,mode="retrospective"))
        await worker.seed()
        job=await self.store.claim()
        try:await dispatch(worker,job)
        finally:await worker.collector.close()
        self.assertEqual((await self.store.fetch("SELECT count(*) AS n FROM surveillance_retrospectives WHERE status='no_observed_trades'"))[0]['n'],20)
        self.assertEqual((await self.store.fetch("SELECT status FROM surveillance_retrospectives WHERE id='positive'"))[0]['status'],'collecting')
