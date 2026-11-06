import os
import unittest

from surveillance.tests import test_postgres as pg
from surveillance.retrospective import handoff
from surveillance.worker import Worker
from dataclasses import replace


@unittest.skipUnless(os.getenv('SURVEILLANCE_TEST_DATABASE_URL'),'Postgres required')
class PipelineTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=pg.PostgresTests.asyncSetUp
    asyncTearDown=pg.PostgresTests.asyncTearDown

    async def test_handoff_releases_collection_and_preserves_analysis_checkpoint(self):
        async with self.store.connection() as c:
            await c.execute("INSERT INTO surveillance_retrospectives(id,venue,market_id,status,document) VALUES('r','kalshi','m','collecting','{}')")
        await self.store.enqueue('collect','retrospective','kalshi',{'review_id':'r','market_id':'m'})
        job=await self.store.claim()
        worker=Worker(self.settings)
        checkpoint=dict(stage='analyze',continuity_version=1,next_end='2026-11-01T00:00:00+00:00')
        try:
            await handoff(worker,job,checkpoint)
            self.assertIsNone(await self.store.claim(exclude_kinds=['retrospective_analysis']))
            analysis=await self.store.claim(kinds=['retrospective_analysis'])
            self.assertEqual(analysis['checkpoint'],checkpoint)
            progressed=dict(checkpoint,next_end='2026-10-31T00:00:00+00:00')
            await self.store.checkpoint(analysis,progressed)
            await handoff(worker,job,checkpoint)
            rows=await self.store.fetch("SELECT checkpoint FROM surveillance_jobs WHERE id='analysis:r'")
            self.assertEqual(rows[0]['checkpoint'],progressed)
        finally:await worker.collector.close()

    async def test_analysis_worker_does_not_seed_or_claim_collection(self):
        await self.store.enqueue('collect','retrospective','kalshi',{'review_id':'r'})
        worker=Worker(replace(self.settings,worker_role='analysis'))
        try:
            await worker.seed()
            self.assertEqual(len(await self.store.fetch('SELECT id FROM surveillance_jobs')),1)
            self.assertFalse(await worker.run_once())
            self.assertEqual((await self.store.claim())['id'],'collect')
        finally:await worker.collector.close()


class WorkerLockRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_polls_again_after_claim_lock_timeout(self):
        import asyncio
        from unittest.mock import AsyncMock, patch
        from psycopg.errors import LockNotAvailable

        worker = object.__new__(Worker)
        worker.seed = AsyncMock()
        worker.collector = AsyncMock()
        worker.run_once = AsyncMock(side_effect=[LockNotAvailable(), asyncio.CancelledError()])
        with patch('surveillance.worker.asyncio.sleep', new_callable=AsyncMock) as sleep:
            with self.assertRaises(asyncio.CancelledError):
                await worker.run()
        sleep.assert_awaited_once_with(2)
        self.assertEqual(worker.run_once.await_count, 2)
        worker.collector.close.assert_awaited_once()
