"""Regression coverage for cash units, delayed knowledge, bounded multi-day evidence."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import os
import unittest
from unittest.mock import patch

from psycopg.types.json import Jsonb
from surveillance.tests import test_postgres as pg
from surveillance.tests import test_event_review as reviews
from surveillance.tests.test_core import poly,kalshi,T
from surveillance.normalization import trade,market,now
from surveillance.money import cash
from surveillance.detectors import evaluate,automatic_candidate
from surveillance.investigations import replay
from surveillance.longitudinal import find_accumulations,record_event,wallet_patterns,refresh_pattern_cases,queue_resolution
from surveillance.screening import scan

W='0x'+'a'*40


class SignalUnitTests(unittest.TestCase):
    def fills(self,received=None):
        return [dict(trade('polymarket',dict(poly(),timestamp=int((T-timedelta(seconds=55-i*10)).timestamp()),price=.3+i*.03,size=1000),received or T.isoformat()),id=str(i)) for i in range(6)]

    def test_kalshi_actual_outcome_cash_and_legacy_fallback(self):
        yes=trade('kalshi',kalshi(yes_price_dollars='.2',count_fp='100'),T.isoformat())
        no=trade('kalshi',kalshi(yes_price_dollars='.2',no_price_dollars='.8',count_fp='100',taker_outcome_side='no',taker_book_side='ask'),T.isoformat())
        self.assertEqual(cash(yes),Decimal(20));self.assertEqual(cash(no),Decimal(80))
        for key in ('cash_price','cash_notional','cash_basis'):no.pop(key,None)
        self.assertEqual(cash(no),Decimal(80))
        no['direction']=None;self.assertIsNone(cash(no))

    def test_unknown_baseline_is_not_observed_zero(self):
        rows=self.fills()
        unknown=evaluate(rows,T.isoformat())[0]
        self.assertEqual(unknown['baseline_cash_buckets'],[None]*12)
        self.assertFalse(automatic_candidate(unknown))
        observed=evaluate(rows,T.isoformat(),coverage=[(T-timedelta(hours=13),T)])[0]
        self.assertEqual(observed['baseline_cash_buckets'],[0]*12)
        self.assertEqual(observed['baseline_observed_windows'],12)
        self.assertTrue(automatic_candidate(observed));self.assertGreater(observed['anomaly_score'],90)
        partial=evaluate(rows,T.isoformat(),coverage=[(T-timedelta(seconds=90),T)])[0]
        self.assertEqual(partial['baseline_observed_windows'],0)
        self.assertTrue(partial['current_fully_observed'])

    def test_receipt_clock_and_sustained_direction(self):
        late=(T+timedelta(minutes=5)).isoformat()
        self.assertEqual(evaluate(self.fills(late),T.isoformat()),[])
        signal=evaluate(self.fills(late),T.isoformat(),knowledge_cutoff=late,coverage=[(T-timedelta(hours=13),T)])[0]
        self.assertEqual(signal['detected_with_delay_seconds'],300)
        rows=self.fills()
        for i,r in enumerate(rows):r['price']=str(.6-i*.03)
        signal=evaluate(rows,T.isoformat(),coverage=[(T-timedelta(hours=13),T)])[0]
        self.assertFalse(signal['price_direction_agrees']);self.assertFalse(signal['price_move_sustained'])
        self.assertEqual(signal['anomaly_score'],80)

    def test_settlement_requires_final_exact_valid_source_prices(self):
        row=dict(id='1',outcomes=['Yes','No'],outcomePrices=['1','0'],umaResolutionStatus='resolved')
        self.assertEqual(market('polymarket',row,now())['resolved_outcome'],'Yes')
        for overrides in (dict(umaResolutionStatus='open'),dict(outcomePrices=['.999','.001']),dict(outcomePrices=[None,'0']),dict(outcomePrices=['NaN','0'])):
            self.assertIsNone(market('polymarket',dict(row,**overrides),now())['resolved_outcome'])


@unittest.skipUnless(os.getenv('SURVEILLANCE_TEST_DATABASE_URL'),'PostgreSQL test DSN required')
class QualityPostgresTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=pg.PostgresTests.asyncSetUp
    asyncTearDown=pg.PostgresTests.asyncTearDown
    job=pg.PostgresTests.job
    info=reviews.ReviewTests.info

    async def intake(self,key,times,market_id='c1',wallet=W,side='BUY',quantity=1000,price=.5,walk=None):
        job=await self.job(key)
        raw=self.archive.write('polymarket','test',{},200,key.encode())
        rows=[dict(trade('polymarket',dict(poly(),timestamp=int(t.timestamp()),condition_id=market_id,proxy_wallet=wallet,side=side,size=quantity,price=price),raw['received_at']),id=key+str(i)) for i,t in enumerate(times)]
        if walk:walk=dict(walk,raw_ids=[raw['id']])
        await self.store.commit_page(job,raw,{},trades=rows,completed_walk=walk)
        await self.store.release(job,3600)
        return job,raw,rows

    async def catalog(self,market_id='c1',event='E',resolved=None):
        job=await self.job('catalog'+market_id+str(resolved))
        raw=self.archive.write('polymarket','test',{},200,(market_id+str(resolved)).encode())
        row=dict(id='m'+market_id,conditionId=market_id,events=[{'id':event}],outcomes=['Yes','No'],question='Policy approval',volume24hr=100)
        if resolved:row.update(umaResolutionStatus='resolved',outcomePrices=['1','0'] if resolved=='Yes' else ['0','1'],closed=True)
        await self.store.commit_page(job,raw,{},markets=[market('polymarket',row,raw['received_at'])],detailed=True)
        await self.store.release(job,3600)

    async def test_duplicate_pages_do_not_inflate_daily_or_multi_day_candidates(self):
        recent=datetime.now(timezone.utc)-timedelta(hours=2)
        times=[recent-timedelta(days=2),recent-timedelta(days=1),recent]
        job,raw,rows=await self.intake('slow',times)
        async with self.store.connection() as c:
            await c.execute('UPDATE surveillance_jobs SET due_at=now() WHERE id=%s',(job['id'],))
        job=await self.store.claim()
        await self.store.commit_page(job,raw,{},trades=rows)
        await self.store.release(job,3600)
        cells=await self.store.fetch('SELECT * FROM surveillance_wallet_daily')
        self.assertEqual(sum(c['fills'] for c in cells),3)
        self.assertEqual((await find_accumulations(self.store))['candidates'],1)
        case=(await self.store.fetch('SELECT document FROM surveillance_cases'))[0]['document']
        self.assertEqual(case['kind'],'slow_accumulation');self.assertIsNone(case['anomaly_score'])
        await self.intake('exit',[recent+timedelta(minutes=1)],side='SELL',quantity=3000)
        self.assertEqual((await find_accumulations(self.store))['candidates'],0)

    async def test_daily_cap_allows_existing_cells_but_not_new_wallets(self):
        recent=datetime.now(timezone.utc)-timedelta(minutes=1)
        with patch('surveillance.longitudinal.DAILY_LIMIT',1):
            await self.intake('one',[recent])
            await self.intake('two',[recent],wallet='0x'+'b'*40)
            await self.intake('three',[recent])
        cells=await self.store.fetch('SELECT * FROM surveillance_wallet_daily')
        self.assertEqual(len(cells),1);self.assertEqual(cells[0]['fills'],2)
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_coverage WHERE kind='wallet_rollup_capacity'")),1)

    async def test_delayed_replay_uses_knowledge_clock_and_preserves_source_head(self):
        cutoff=datetime.now(timezone.utc).replace(second=0,microsecond=0)-timedelta(minutes=5)
        walk=dict(lower_time=(cutoff-timedelta(hours=13)).isoformat(),upper_time=now(),source_upper=cutoff.isoformat(),refs_complete=True,observed_trades=6)
        await self.intake('late',[cutoff-timedelta(seconds=55-i*9) for i in range(6)],walk=walk)
        self.assertEqual(await replay(self.store,'polymarket','c1',cutoff.isoformat()),[])
        cases=await replay(self.store,'polymarket','c1',cutoff.isoformat(),knowledge_cutoff=now(),persist=False)
        self.assertTrue(cases);self.assertTrue(cases[0]['signal']['current_fully_observed'])
        self.assertGreaterEqual(cases[0]['signal']['detected_with_delay_seconds'],300)
        self.assertNotIn('detected_at',cases[0])
        observation=(await self.store.fetch('SELECT * FROM surveillance_observations'))[0]
        self.assertEqual(observation['upper_time'],cutoff)

    async def test_outside_pool_scan_bounded_and_does_not_change_selection(self):
        for i in range(24):await self.catalog('c'+str(i),event='E'+str(i))
        async with self.store.connection() as c:
            await c.execute("INSERT INTO surveillance_scout SELECT 'polymarket','c'||i,now(),now(),5,2000,now() FROM generate_series(0,23) i")
        await self.store.enqueue('deep','detect','polymarket',dict(market_id='c0'))
        self.assertEqual((await scan(self.store,'polymarket'))['admitted'],20)
        self.assertEqual((await scan(self.store,'polymarket'))['admitted'],0)
        jobs=await self.store.fetch("SELECT payload FROM surveillance_jobs WHERE kind='scout_detect'")
        self.assertEqual(len(jobs),20);self.assertNotIn('c0',[r['payload']['market_id'] for r in jobs])
        async with self.store.connection() as c:
            await c.execute("UPDATE surveillance_jobs SET enabled=false WHERE kind='scout_detect'")
        self.assertEqual((await scan(self.store,'polymarket'))['admitted'],3)
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_jobs WHERE kind='detect' AND enabled")),1)

    async def test_event_results_no_backdated_alert_and_same_event_counts_once(self):
        anchor=datetime.now(timezone.utc)-timedelta(hours=1)
        await self.catalog();await self.intake('before',[anchor-timedelta(hours=1)])
        await self.info(anchor)
        await record_event(self.store,'notice',now())
        before=now()
        self.assertEqual((await wallet_patterns(self.store,W))['unknown'],1)
        await self.catalog(resolved='Yes');await record_event(self.store,'notice',now())
        result=await wallet_patterns(self.store,W)
        self.assertEqual(result['matches'],1);self.assertEqual(result['independent_events'],1)
        self.assertIsNone(result['events'][0]['document']['actual_alert_before_anchor'])
        self.assertFalse(result['events'][0]['document']['all_receipts_before_anchor'])
        self.assertEqual((await wallet_patterns(self.store,W,before))['unknown'],1)
        await self.info(anchor+timedelta(minutes=1),key='later')
        self.assertEqual((await record_event(self.store,'later',now()))['status'],'earlier_verified_anchor_already_recorded')
        self.assertEqual((await record_event(self.store,'notice',now()))['updated'],0)

    async def test_repeated_matches_include_losses_and_avoid_version_churn(self):
        anchor=datetime.now(timezone.utc)-timedelta(hours=1)
        for i in range(4):
            key='c'+str(i)
            await self.catalog(key,'E'+str(i),resolved='Yes' if i<3 else 'No')
            await self.intake('buy'+str(i),[anchor-timedelta(hours=1)],market_id=key)
            await self.info(anchor,market_id=key,key='notice'+str(i))
            await record_event(self.store,'notice'+str(i),now())
        summary=await wallet_patterns(self.store,W)
        self.assertEqual((summary['matches'],summary['mismatches'],summary['evaluable_events']),(3,1,4))
        self.assertTrue(summary['repeated_settlement_matches'])
        self.assertEqual((await refresh_pattern_cases(self.store))['pattern_candidates'],1)
        self.assertEqual((await refresh_pattern_cases(self.store))['pattern_candidates'],0)
        case=(await self.store.fetch('SELECT document FROM surveillance_cases'))[0]['document']
        self.assertIsNone(case['anomaly_score']);self.assertEqual(case['summary']['mismatches'],1)

    async def test_resolution_refresh_queue_is_bounded_and_not_reenabled_early(self):
        markets=[dict(id=str(i),resolved_outcome=None) for i in range(25)]
        self.assertEqual((await queue_resolution(self.store,markets))['pending'],20)
        async with self.store.connection() as c:
            await c.execute("UPDATE surveillance_jobs SET enabled=false")
        # Existing jobs are cooling down; five previously unqueued contracts fit.
        self.assertEqual((await queue_resolution(self.store,markets))['pending'],5)


    async def test_observation_pin_survives_retention_then_fifo_expires_case(self):
        from surveillance.maintenance import prune
        from surveillance.capacity import evict_batch
        cutoff=datetime.now(timezone.utc)-timedelta(days=10)
        job=await self.job('observation')
        raw=self.archive.write('polymarket','test',{},200,b'observation only',cutoff.isoformat())
        await self.store.commit_page(job,raw,{},completed_walk=dict(lower_time=(cutoff-timedelta(hours=1)).isoformat(),
            upper_time=cutoff.isoformat(),source_upper=cutoff.isoformat(),raw_ids=[raw['id']],refs_complete=True,observed_trades=0))
        observation=(await self.store.fetch('SELECT id FROM surveillance_observations'))[0]['id']
        await self.store.save_case(dict(id='pinned',venue='polymarket',market_id='c1',observation_ids=[observation]))
        async with self.store.connection() as c:
            await c.execute('UPDATE surveillance_observations SET known_at=%s',(cutoff,))
        self.assertEqual((await prune(self.store))['expired_raw_receipts'],0)
        self.assertEqual(len(await self.store.fetch('SELECT * FROM surveillance_observations')),1)
        async with self.store.connection() as c:self.assertEqual(await evict_batch(c,1),1)
        self.assertFalse(await self.store.fetch('SELECT * FROM surveillance_observations'))
        self.assertFalse(await self.store.fetch('SELECT * FROM surveillance_cases'))

    async def test_legacy_no_trade_aggregate_cash_is_corrected_without_rewriting_fill_id(self):
        from surveillance.aggregates import materialize
        cutoff=datetime.now(timezone.utc)-timedelta(hours=1)
        job=await self.job('no-trade',venue='kalshi')
        raw=self.archive.write('kalshi','test',{},200,b'NO trade')
        row=trade('kalshi',kalshi(yes_price_dollars='.2',count_fp='100',taker_outcome_side='no',taker_book_side='ask',created_time=cutoff.isoformat()),now())
        identity=row['identity']
        for key in ('cash_price','cash_notional','cash_basis'):row.pop(key,None)
        row['id']=identity
        await self.store.commit_page(job,raw,{},trades=[row])
        await materialize(self.store)
        agg=(await self.store.fetch('SELECT document FROM surveillance_aggregates'))[0]['document']
        self.assertEqual(Decimal(agg['cash']),80);self.assertEqual(agg['aggregation_version'],'cash-v2')
        self.assertEqual((await self.store.fetch('SELECT id FROM surveillance_trades'))[0]['id'],identity)


    async def test_alert_cooldown_is_per_detector_version(self):
        doc=dict(id='v1',venue='polymarket',market_id='c1',outcome_key='yes',anomaly_score=100,
            signal=dict(window_seconds=60,detector_version='surveillance-v1.1'))
        self.assertTrue(await self.store.save_candidate(doc))
        changed=dict(doc,id='v2',anomaly_score=50,signal=dict(window_seconds=60,detector_version='surveillance-v2.0'))
        self.assertTrue(await self.store.save_candidate(changed))
        self.assertFalse(await self.store.save_candidate(dict(changed,id='v2-duplicate')))
