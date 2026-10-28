"""Run with SURVEILLANCE_TEST_DATABASE_URL; every test owns its own SQL schema."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

import httpx
import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from surveillance.api import create_app
from surveillance.collectors import Collector
from surveillance.config import Settings
from surveillance.investigations import replay
from surveillance.normalization import now, market, trade
from surveillance.storage import Store, RawArchive
from surveillance.worker import Worker
from surveillance.tests.test_core import poly, kalshi


@unittest.skipUnless(os.getenv("SURVEILLANCE_TEST_DATABASE_URL"), "PostgreSQL test DSN required")
class PostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.base = os.environ["SURVEILLANCE_TEST_DATABASE_URL"]
        self.schema = "surveillance_test_" + uuid.uuid4().hex
        async with await psycopg.AsyncConnection.connect(self.base) as c:
            await c.execute(f'CREATE SCHEMA "{self.schema}"')
        self.dsn = make_conninfo(self.base, options=f"-csearch_path={self.schema}")
        self.store = Store(self.dsn)
        await self.store.initialize()
        self.folder = tempfile.TemporaryDirectory()
        self.archive = RawArchive(self.folder.name)
        self.settings = Settings(self.dsn, Path(self.folder.name), request_interval=0, pages_per_job=1)

    async def asyncTearDown(self):
        async with await psycopg.AsyncConnection.connect(self.base) as c:
            await c.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.folder.cleanup()

    async def job(self, key="t1", kind="trades", venue="polymarket"):
        await self.store.enqueue(key, kind, venue, {"market_id": "c1"})
        return await self.store.claim()

    async def test_lease_exclusion_recovery_and_fencing(self):
        first = await self.job()
        self.assertIsNone(await self.store.claim())
        async with self.store.connection() as c:
            await c.execute("UPDATE surveillance_jobs SET lease_until=now()-interval '1 second'")
        second = await self.store.claim()
        self.assertNotEqual(first["lease_token"], second["lease_token"])
        raw = self.archive.write("polymarket", "test", {}, 200, b"{}")
        with self.assertRaises(RuntimeError):
            await self.store.commit_page(first, raw, {"cursor": "lost"})
        await self.store.commit_page(second, raw, {"cursor": "won"})
        self.assertEqual((await self.store.fetch("SELECT checkpoint FROM surveillance_jobs"))[0]["checkpoint"]["cursor"], "won")

    async def test_page_rollback_keeps_checkpoint_and_raw(self):
        job = await self.job()
        raw = self.archive.write("polymarket", "test", {}, 200, b"{}")
        await self.store.raw(raw)
        t = trade("polymarket", poly(), now())
        t["id"] = "good"
        bad = dict(t, id="bad", event_time="invalid")
        with self.assertRaises(Exception):
            await self.store.commit_page(job, raw, {"cursor": "next"}, trades=[t, bad])
        self.assertEqual(await self.store.fetch("SELECT * FROM surveillance_trades"), [])
        self.assertEqual((await self.store.fetch("SELECT checkpoint FROM surveillance_jobs"))[0]["checkpoint"], {})
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_raw")), 1)

    async def test_restart_v2_pagination_multiplicity_and_repoll(self):
        calls = []
        row = dict(poly(), timestamp=int(datetime.now(timezone.utc).timestamp()) - 10)
        def handler(request):
            calls.append(dict(request.url.params))
            cursor = request.url.params.get("cursor")
            if cursor == "b":
                data, nxt = [row], None
            else:
                data, nxt = [row, row], "b"
            return httpx.Response(200, json={"data": data, "pagination": {"has_more": bool(nxt), "next_cursor": nxt}})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        collector = Collector(self.store, self.archive, 0, client)
        worker = Worker(self.settings, collector)
        job = await self.job()
        self.assertEqual(await worker.ingest(job), 1)
        saved = (await self.store.fetch("SELECT checkpoint FROM surveillance_jobs"))[0]["checkpoint"]
        self.assertEqual(saved["cursor"], "b")
        # A fresh worker/store instance consumes the database checkpoint.
        await self.store.release(job, 0)
        resumed = await Store(self.dsn).claim()
        await Worker(self.settings, collector).ingest(resumed)
        self.assertEqual(calls[-1]["cursor"], "b")
        self.assertEqual(calls[0]["condition"], calls[-1]["condition"])
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_trades")), 3)
        await self.store.release(resumed, 0)
        repeat = await self.store.claim()
        await worker.ingest(repeat)
        repeat = (await self.store.fetch("SELECT * FROM surveillance_jobs"))[0]
        await worker.ingest(repeat)
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_trades")), 3)
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_raw")), 4)
        await collector.close()

    async def test_schema_error_records_gap_without_cursor_advance(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []})))
        worker = Worker(self.settings, Collector(self.store, self.archive, 0, client))
        await self.store.enqueue("t1", "trades", "polymarket", {"market_id": "c1"})
        await worker.run_once()
        row = (await self.store.fetch("SELECT * FROM surveillance_jobs"))[0]
        self.assertEqual(row["failures"], 1)
        self.assertIn("since", row["checkpoint"])
        self.assertNotIn("cursor", row["checkpoint"])
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_raw")), 1)
        self.assertEqual((await self.store.fetch("SELECT kind FROM surveillance_coverage ORDER BY id DESC"))[0]["kind"], "error")
        await worker.collector.close()

    async def test_case_replay_review_and_api(self):
        cutoff = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=2)
        observed = (cutoff - timedelta(seconds=1)).isoformat()
        job = await self.job(venue="kalshi")
        raw = self.archive.write("kalshi", "test", {}, 200, b"{}", observed)
        trades = []
        for i in range(10):
            row = kalshi(trade_id=f"kt{i}", created_time=(cutoff - timedelta(seconds=20-i)).isoformat(),
                         yes_price_dollars=str(0.3 + i * 0.03), ticker="c1")
            trades.append(dict(trade("kalshi", row, observed), id=f"kt{i}"))
        m = market("kalshi", {"ticker": "c1", "event_ticker": "e1", "rules_primary": "old rules", "title": "Policy announcement"}, observed)
        await self.store.commit_page(job, raw, {}, markets=[m], trades=trades)
        # A subsequent rule snapshot must not leak into the historical case.
        changed = dict(m, rules={"rules_primary": "future rules"}, rules_hash="new", observed_at=now())
        await self.store.commit_page(job, raw, {}, markets=[changed])
        cases = await replay(self.store, "kalshi", "c1", cutoff.isoformat())
        self.assertTrue(cases)
        self.assertEqual(cases[0]["rules"]["rules_primary"], "old rules")
        self.assertEqual(cases, await replay(self.store, "kalshi", "c1", cutoff.isoformat()))
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_cases")), len(cases))
        settings = Settings(self.dsn, Path(self.folder.name), api_token="test-token")
        app = create_app(settings)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            self.assertEqual((await client.get("/health")).status_code, 401)
            client.headers["Authorization"] = "Bearer test-token"
            self.assertEqual((await client.get("/health")).json()["trading"], False)
            case_id = cases[0]["id"]
            response = await client.post(f"/cases/{case_id}/review", json={"status": "dismissed", "note": "Public information found", "reviewer": "human"})
            self.assertEqual(response.json()["version"], 2)
            self.assertNotIn("review", (await client.get(f"/cases/{case_id}?version=1")).json())
            self.assertIn("not probabilities", (await client.get(f"/cases/{case_id}/report")).text)
            self.assertEqual((await client.get(f"/evidence/{raw['id']}")).json()["body"], "{}")
            bad = await client.post("/replay", json={"venue": "kalshi", "market_id": "c1", "as_of": "2026-10-28T00:00:00"})
            self.assertEqual(bad.status_code, 422)
            info = await client.post("/information", json={"venue": "kalshi", "market_id": "c1", "source_url": "https://example.test/official", "title": "Notice", "content": "Evidence", "published_at": "2026-10-01T12:00:00Z"})
            self.assertEqual(info.status_code, 200)
            attached = await client.post(f"/cases/{case_id}/information/{info.json()['id']}")
            self.assertEqual(attached.status_code, 200)
            self.assertEqual(attached.json()["anomaly_score"], cases[0]["anomaly_score"])
            self.assertEqual(len(attached.json()["investigation_timeline"]), 1)
            self.assertEqual(attached.json()["public_timeline"], [])
            # Our later intake must not appear in an earlier replay even with an old claimed publication date.
            again = await replay(self.store, "kalshi", "c1", cutoff.isoformat(), persist=False)
            self.assertEqual(again[0]["public_timeline"], [])

    async def test_catalog_partitions_and_budget_schedule(self):
        requested = []
        def handler(request):
            closed = request.url.params["closed"] == "true"
            requested.append(closed)
            rows = [{"id": ("closed" if closed else "open") + str(i), "conditionId": f"c{closed}{i}",
                     "question": "Unfiltered event", "events": [{"id": "same-event"}], "closed": closed,
                     "outcomes": '["A","B","C"]', "clobTokenIds": '["1","2","3"]'} for i in range(4)]
            return httpx.Response(200, json={"markets": rows})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        settings = Settings(self.dsn, Path(self.folder.name), contracts_per_venue=2, pages_per_job=1)
        worker = Worker(settings, Collector(self.store, self.archive, 0, client))
        for closed in (False, True):
            await self.store.enqueue(f"catalog:{closed}", "catalog", "polymarket", {"closed": closed})
            job = await self.store.claim()
            await worker.ingest(job)
            await self.store.release(job, 3600)
        self.assertEqual(requested, [False, True])
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_markets")), 8)
        await worker.schedule("polymarket")
        jobs = await self.store.fetch("SELECT * FROM surveillance_jobs WHERE kind='trades' AND enabled")
        self.assertEqual(len(jobs), 2)
        self.assertTrue(all("False" in r["payload"]["market_id"] for r in jobs))
        await worker.collector.close()

    async def test_unchanged_rules_do_not_duplicate_but_reversions_survive(self):
        job = await self.job(venue="kalshi")
        raw = self.archive.write("kalshi", "test", {}, 200, b"{}")
        t = datetime.now(timezone.utc)
        old = market("kalshi", {"ticker": "c1", "event_ticker": "e1", "rules_primary": "old"}, t.isoformat())
        await self.store.commit_page(job, raw, {}, markets=[old])
        await self.store.commit_page(job, raw, {}, markets=[dict(old, observed_at=(t+timedelta(seconds=1)).isoformat())])
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_rules")), 1)
        changed = market("kalshi", {"ticker": "c1", "event_ticker": "e1", "rules_primary": "new"}, (t+timedelta(seconds=2)).isoformat())
        await self.store.commit_page(job, raw, {}, markets=[changed])
        await self.store.commit_page(job, raw, {}, markets=[dict(old, observed_at=(t+timedelta(seconds=3)).isoformat())])
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_rules")), 3)

    async def test_automatic_case_coalescing_preserves_stronger_signal(self):
        case = dict(id="case1", venue="kalshi", market_id="c1", outcome_key="yes", anomaly_score=40,
                    signal={"window_seconds":60})
        self.assertTrue(await self.store.save_candidate(case))
        self.assertFalse(await self.store.save_candidate(dict(case, id="case2", anomaly_score=55)))
        self.assertTrue(await self.store.save_candidate(dict(case, id="case3", anomaly_score=65)))
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_cases")), 2)

    async def test_retention_preserves_referenced_and_shared_raw_blobs(self):
        from surveillance.maintenance import prune
        old_time = (datetime.now(timezone.utc)-timedelta(days=10)).isoformat()
        old = self.archive.write("kalshi", "old", {}, 200, b"shared", old_time)
        shared = self.archive.write("kalshi", "recent", {}, 200, b"shared")
        unpinned = self.archive.write("kalshi", "old", {}, 200, b"unused", old_time)
        pinned = self.archive.write("kalshi", "old", {}, 200, b"case input", old_time)
        for raw in (old, shared, unpinned, pinned):
            await self.store.raw(raw)
        await self.store.save_case(dict(id="pin",venue="kalshi",market_id="c1",replay_raw_ids=[pinned["id"]]))
        result = await prune(self.store)
        self.assertEqual(result["expired_raw_receipts"], 2)
        self.assertTrue(Path(shared["path"]).exists())
        self.assertTrue(Path(pinned["path"]).exists())
        self.assertFalse(Path(unpinned["path"]).exists())
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_raw")), 2)

    async def test_replay_capacity_is_explicit_not_silent_truncation(self):
        from surveillance.investigations import ReplayCapacityError
        cutoff=datetime.now(timezone.utc)
        job=await self.job(venue="kalshi")
        raw=self.archive.write("kalshi","test",{},200,b"{}")
        trades=[dict(trade("kalshi",kalshi(trade_id=str(i),ticker="c1",created_time=(cutoff-timedelta(seconds=10)).isoformat()),
                          (cutoff-timedelta(seconds=1)).isoformat()),id=str(i)) for i in range(6)]
        await self.store.commit_page(job,raw,{},trades=trades)
        with self.assertRaises(ReplayCapacityError):
            await replay(self.store,"kalshi","c1",cutoff.isoformat(),max_trades=5)
        self.assertEqual(await self.store.fetch("SELECT * FROM surveillance_cases"),[])
