"""Receipt-level rollups: no admission loss, idempotent replay, exact FIFO retraction."""
from datetime import datetime,timedelta,timezone
import os,unittest
from psycopg.types.json import Jsonb
from surveillance.tests import test_postgres as pg
from surveillance.tests import test_signal_quality as quality
from surveillance.normalization import trade,now
from surveillance.tests.test_core import poly
from surveillance.longitudinal import backfill_daily,receipt_parts
from surveillance.capacity import evict_batch
from surveillance.investigations import replay

W='0x'+'a'*40


@unittest.skipUnless(os.getenv('SURVEILLANCE_TEST_DATABASE_URL'),'PostgreSQL test DSN required')
class WalletCoverageTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=pg.PostgresTests.asyncSetUp
    asyncTearDown=pg.PostgresTests.asyncTearDown
    job=pg.PostgresTests.job
    intake=quality.QualityPostgresTests.intake

    async def retained_only(self,key,times):
        raw=self.archive.write('polymarket','test',{},200,key.encode())
        await self.store.raw(raw)
        rows=[dict(trade('polymarket',dict(poly(),proxy_wallet=W,timestamp=int(t.timestamp()),size=1000,price=.5),raw['received_at']),id=key+str(i)) for i,t in enumerate(times)]
        async with self.store.connection() as c:
            for t in rows:await c.execute('INSERT INTO surveillance_trades VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                ('polymarket',t['id'],t['market_id'],t['outcome'],t['event_time'],t['received_at'],Jsonb(t),raw['id']))
        return raw

    async def test_backfill_and_live_ingestion_never_double_count(self):
        current=datetime.now(timezone.utc)-timedelta(minutes=1)
        old=await self.retained_only('missed',[current-timedelta(days=1),current-timedelta(hours=1),current])
        await self.intake('live',[current])
        await self.store.enqueue('rebuild','wallet_rollup_backfill','polymarket',{})
        j=await self.store.claim()
        first=await backfill_daily(self.store,j,limit=1)
        self.assertEqual(first['eligible_fills'],3);self.assertFalse(first['done'])
        await self.store.release(j,0)
        j=await self.store.claim();second=await backfill_daily(self.store,j,limit=1)
        self.assertTrue(second['done'])
        async with self.store.connection() as c:self.assertTrue((await receipt_parts(c,old['id']))['duplicate'])
        self.assertEqual((await self.store.fetch('SELECT sum(fills) AS n FROM surveillance_wallet_daily'))[0]['n'],4)
        self.assertEqual((await self.store.fetch('SELECT count(*) AS n FROM surveillance_wallet_daily_receipts'))[0]['n'],2)

    async def test_fifo_keeps_newer_contribution_to_the_same_cell(self):
        current=datetime.now(timezone.utc)-timedelta(minutes=1)
        _,old,_=await self.intake('older',[current,current])
        _,new,_=await self.intake('newer',[current,current,current])
        async with self.store.connection() as c:
            await c.execute("UPDATE surveillance_raw SET received_at='2020-01-01' WHERE id=%s",(old['id'],))
            await evict_batch(c,1)
        rows=await self.store.fetch('SELECT fills,buy_cash,raw_ids FROM surveillance_wallet_daily')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['fills'],3)
        self.assertEqual(rows[0]['buy_cash'],1500);self.assertEqual(rows[0]['raw_ids'],[new['id']])

    async def test_legacy_partial_summary_is_superseded_and_rebuilt_from_sources(self):
        current=datetime.now(timezone.utc)-timedelta(minutes=1)
        await self.retained_only('source',[current])
        await self.store.save_case(dict(id='legacy',venue='polymarket',market_id='c1',kind='slow_accumulation',status='candidate'))
        async with self.store.connection() as c:
            await c.execute('DROP VIEW surveillance_wallet_daily')
            await c.execute('CREATE TABLE surveillance_wallet_daily(dummy integer)')
            await c.execute('DELETE FROM surveillance_schema WHERE version=6')
        await self.store.initialize()
        case=(await self.store.fetch("SELECT document FROM surveillance_cases WHERE id='legacy'"))[0]['document']
        self.assertTrue(case['rollup_superseded'])
        self.assertEqual(len(await self.store.fetch('SELECT * FROM surveillance_case_versions')),2)
        self.assertFalse(await self.store.fetch('SELECT * FROM surveillance_wallet_daily'))
        await self.store.enqueue('repair','wallet_rollup_backfill','polymarket',{})
        await backfill_daily(self.store,await self.store.claim())
        self.assertEqual((await self.store.fetch('SELECT sum(fills) AS n FROM surveillance_wallet_daily'))[0]['n'],1)

    async def test_more_than_the_former_200000_cells_are_admitted(self):
        raw=self.archive.write('polymarket','test',{},200,b'large bounded fixture')
        await self.store.raw(raw)
        async with self.store.connection() as c:
            await c.execute("""INSERT INTO surveillance_wallet_daily_parts SELECT %s,
                '0x'||lpad(to_hex(i),40,'0'),'m','t','Yes',(now() AT TIME ZONE 'UTC')::date,
                now(),now(),now(),1,1,0,2,0,1 FROM generate_series(1,200000) i""",(raw['id'],))
        current=datetime.now(timezone.utc)-timedelta(minutes=1)
        await self.intake('new-cell',[current],wallet='0x'+'f'*40)
        self.assertEqual((await self.store.fetch('SELECT count(*) AS n FROM surveillance_wallet_daily'))[0]['n'],200001)

    async def test_busy_market_keeps_complete_shorter_windows(self):
        cutoff=datetime.now(timezone.utc).replace(second=0,microsecond=0)-timedelta(minutes=1)
        older=[cutoff-timedelta(hours=2,seconds=i) for i in range(60)]
        recent=[cutoff-timedelta(seconds=55-i*8) for i in range(7)]
        walk=dict(lower_time=(cutoff-timedelta(hours=13)).isoformat(),upper_time=cutoff.isoformat(),source_upper=cutoff.isoformat(),refs_complete=True,observed_trades=67)
        await self.intake('hot',older+recent,walk=walk)
        diagnostics={}
        cases=await replay(self.store,'polymarket','c1',cutoff.isoformat(),knowledge_cutoff=now(),persist=False,max_trades=50,diagnostics=diagnostics)
        self.assertTrue(cases)
        self.assertEqual(diagnostics['replay_horizon_minutes'],65)
        self.assertEqual(diagnostics['omitted_windows_seconds'],[3600])
        self.assertTrue(all(c['signal']['window_seconds'] in (60,300) for c in cases))
        self.assertTrue(all(c['omitted_windows_seconds']==[3600] for c in cases))


    async def test_minimum_baseline_fallback_does_not_zero_fill_unread_history(self):
        cutoff=datetime.now(timezone.utc).replace(second=0,microsecond=0)-timedelta(minutes=1)
        older=[cutoff-timedelta(minutes=10,seconds=i) for i in range(60)]
        recent=[cutoff-timedelta(seconds=55-i*8) for i in range(7)]
        walk=dict(lower_time=(cutoff-timedelta(hours=13)).isoformat(),upper_time=cutoff.isoformat(),source_upper=cutoff.isoformat(),refs_complete=True,observed_trades=67)
        await self.intake('very-hot',older+recent,walk=walk)
        cases=await replay(self.store,'polymarket','c1',cutoff.isoformat(),knowledge_cutoff=now(),persist=False,max_trades=50)
        self.assertTrue(cases)
        self.assertTrue(all(c['replay_horizon_minutes']==7 for c in cases))
        self.assertTrue(all(c['signal']['baseline_observed_windows']==6 for c in cases))
        self.assertTrue(all(c['signal']['baseline_cash_buckets'].count(None)==6 for c in cases))


    async def test_future_source_timestamp_is_retained_but_not_a_current_signal(self):
        from surveillance.longitudinal import find_accumulations
        current=datetime.now(timezone.utc)
        await self.intake('clock-skew',[current-timedelta(days=1),current-timedelta(hours=1),current+timedelta(minutes=1)])
        self.assertEqual((await self.store.fetch('SELECT sum(fills) AS n FROM surveillance_wallet_daily'))[0]['n'],3)
        self.assertEqual((await find_accumulations(self.store))['candidates'],0)
