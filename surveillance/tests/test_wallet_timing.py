import unittest
from surveillance.wallet_timing import measure
from surveillance.tests.test_retrospective import tape


class TimingTests(unittest.TestCase):
    def test_all_sides_include_adverse_markouts_and_control_excludes_self(self):
        rows,start,end=tape()
        # Identical entry times/prices, opposite directions. Both enter the cohort.
        first=dict(rows[0],wallet='a',direction=1)
        second=dict(first,wallet='b',direction=-1,id='opposite')
        third=dict(first,wallet='c',id='peer')
        rows=[dict(t,wallet=None) for t in rows]+[first,second,third]
        result={r['wallet']:r for r in measure(rows,start,end)}
        self.assertGreater(result['a']['price_change_sum'],0)
        self.assertLess(result['b']['price_change_sum'],0)
        self.assertEqual(result['a']['controlled'],1)
        self.assertEqual(result['a']['excess_sum'],0)
        self.assertEqual(result['b']['controlled'],0)

    def test_missing_future_stays_in_denominator(self):
        rows,start,end=tape()
        result=measure(rows,start,end)
        self.assertTrue(any(r['eligible']>r['observed'] for r in result))


class PatternTests(unittest.IsolatedAsyncioTestCase):
    async def test_siblings_count_once_and_negative_event_is_retained(self):
        from surveillance.wallet_timing import patterns
        class Store:
            async def fetch(self,*args):
                return [dict(events=[event],review_id=str(i),slice_id=str(i),document=dict(
                    observed=1,eligible=2,controlled=1,price_change_sum=value,excess_sum=value))
                    for i,(event,value) in enumerate([('same',.1),('same',.2),('loss',-.3)])]
        result=await patterns(Store(),'wallet')
        self.assertEqual(result['independent_native_events'],2)
        self.assertEqual(result['positive_peer_events'],1)
        self.assertEqual(result['negative_peer_events'],1)
        self.assertEqual(result['sample_status'],'insufficient')


import os
from surveillance.tests import test_postgres as pg


@unittest.skipUnless(os.getenv('SURVEILLANCE_TEST_DATABASE_URL'),'Postgres required')
class TimingStorageTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=pg.PostgresTests.asyncSetUp
    asyncTearDown=pg.PostgresTests.asyncTearDown

    async def test_metrics_follow_slice_retention_and_enter_budget(self):
        from surveillance.wallet_timing import persist,patterns
        rows,start,end=tape()
        async with self.store.connection() as c:
            await c.execute("INSERT INTO surveillance_retrospectives(id,venue,market_id,status,document) VALUES('review','polymarket','c1','complete_observed','{\"continuity\":{\"status\":\"verified_api_interval\"},\"market\":{\"event_ids\":[\"e1\"]}}')")
            await c.execute("INSERT INTO surveillance_review_slices(id,review_id,lower_time,upper_time,document) VALUES('slice','review',%s,%s,'{}')",(start,end))
            await persist(c,'slice',rows,start,end)
            await persist(c,'slice',rows,start,end)
        result=await patterns(self.store,'early')
        self.assertEqual(result['independent_native_events'],1)
        async with self.store.connection() as c:
            await c.execute("DELETE FROM surveillance_retrospectives WHERE id='review'")
        self.assertEqual(await self.store.fetch('SELECT * FROM surveillance_wallet_timing'),[])
        rows=await self.store.fetch("SELECT logical_bytes FROM surveillance_research_budget WHERE name='surveillance_wallet_timing'")
        self.assertEqual(rows[0]['logical_bytes'],0)


class HorizonTests(unittest.TestCase):
    def test_short_market_has_short_horizon_observations(self):
        rows,start,end=tape()
        from surveillance.leadlag import epoch,iso
        short_end=iso(epoch(start)+1800)
        short_rows=[r for r in rows if epoch(r['event_time'])<epoch(short_end)]
        long=measure(short_rows,start,short_end,3600)
        short=measure(short_rows,start,short_end,300)
        self.assertEqual(sum(r['observed'] for r in long),0)
        self.assertGreater(sum(r['observed'] for r in short),0)


class LegacyHorizonTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_hour_metric_is_unknown_at_short_horizon(self):
        from surveillance.wallet_timing import patterns
        class Store:
            async def fetch(self,*args):
                return [dict(events=['event'],review_id='r',slice_id='s',document=dict(
                    eligible=1,observed=1,controlled=1,price_change_sum=.1,excess_sum=.1))]
        result=await patterns(Store(),'wallet',300)
        self.assertEqual(result['events'][0]['observed'],0)
        self.assertIsNone(result['events'][0]['mean_price_change'])
