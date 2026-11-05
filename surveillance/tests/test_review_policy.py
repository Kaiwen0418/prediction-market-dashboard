import unittest
from surveillance.review_policy import evaluate


class PolicyTests(unittest.TestCase):
    def test_continuous_prices_excluded(self):
        for title in ('Bitcoin above 78,400 on November 4?', 'Ethereum Up or Down - 15 minutes',
                      'Will Tesla close above $400?', 'Will gold reach $3000?'):
            self.assertFalse(evaluate(dict(id='id',title=title))['eligible'],title)
        self.assertFalse(evaluate(dict(id='KXBTC15M-26NOV05',title='Up?'))['eligible'])

    def test_discrete_information_events_remain_eligible(self):
        for title in ('Will the SEC approve a Bitcoin ETF?', 'Will Tesla announce a stock split?',
                      'Will CEO resign?', 'Team A vs Team B', 'Will a player withdraw?',
                      'Will temperature be above 30C?', 'Will CPI exceed 3%?', 'Who will win the award?'):
            self.assertTrue(evaluate(dict(id='id',title=title))['eligible'],title)


import os
from surveillance.tests import test_postgres as pg


@unittest.skipUnless(os.getenv('SURVEILLANCE_TEST_DATABASE_URL'),'Postgres required')
class PolicyStorageTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=pg.PostgresTests.asyncSetUp
    asyncTearDown=pg.PostgresTests.asyncTearDown

    async def test_sweep_retires_existing_price_review_and_job(self):
        from surveillance.review_policy import sweep
        async with self.store.connection() as c:
            await c.execute("INSERT INTO surveillance_retrospectives(id,venue,market_id,status,document) VALUES('r','polymarket','c','pending','{\"market\":{\"id\":\"c\",\"title\":\"Bitcoin above 100000?\"}}')")
            await c.execute("INSERT INTO surveillance_jobs(id,venue,kind,payload) VALUES('retrospective:r','polymarket','retrospective','{}')")
            result=await sweep(c)
            self.assertEqual(result['excluded'],1)
        self.assertEqual((await self.store.fetch('SELECT status FROM surveillance_retrospectives'))[0]['status'],'excluded')
        self.assertFalse((await self.store.fetch('SELECT enabled FROM surveillance_jobs'))[0]['enabled'])


class ActivityTests(unittest.TestCase):
    def test_only_explicit_zero_is_excluded(self):
        for market in ({'volume':'0'}, {'volume':'0','volume_reported':False}, {'volume':'0.01','volume_reported':True}):
            self.assertTrue(evaluate(market)['eligible'])
        self.assertEqual(evaluate({'volume':'0','volume_reported':True})['reason'],'reported_zero_activity')


@unittest.skipUnless(os.getenv('SURVEILLANCE_TEST_DATABASE_URL'),'Postgres required')
class ReactivationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=pg.PostgresTests.asyncSetUp
    asyncTearDown=pg.PostgresTests.asyncTearDown

    async def test_activity_can_reactivate_excluded_review(self):
        from surveillance.tests.test_retrospective import RetrospectiveTests
        from surveillance.retrospective import register
        from datetime import datetime,timedelta,timezone
        m,raw,_=await RetrospectiveTests.final_market(self)
        async with self.store.connection() as c:
            first=await register(c,dict(m,volume='1',volume_reported=True),raw,self.settings)
            self.assertIsNone(await register(c,dict(m,volume='0',volume_reported=True),raw,self.settings))
            later=dict(raw,received_at=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat())
            again=await register(c,dict(m,volume='2',volume_reported=True),later,self.settings)
            self.assertNotEqual(first,again)
        self.assertEqual((await self.store.fetch('SELECT status FROM surveillance_retrospectives WHERE id=%s',(again,)))[0]['status'],'pending')
