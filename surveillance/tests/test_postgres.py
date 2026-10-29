"""Run with SURVEILLANCE_TEST_DATABASE_URL; every test owns its own SQL schema."""
import asyncio
from datetime import datetime, timedelta, timezone
from dataclasses import replace
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
        self.settings = Settings(self.dsn, Path(self.folder.name), request_interval=0, pages_per_job=1, database_max_bytes=1024**4)

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
        settings = replace(self.settings, api_token="test-token")
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
        settings = replace(self.settings, contracts_per_venue=2, pages_per_job=1)
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

    async def test_capacity_fifo_preserves_newer_shared_blob_and_progress(self):
        from surveillance.capacity import evict_batch, sweep_orphans, TABLES
        from psycopg import sql
        old = self.archive.write("polymarket", "old", {}, 200, b"shared", "2020-01-01T00:00:00+00:00")
        new = self.archive.write("polymarket", "new", {}, 200, b"shared")
        await self.store.raw(old)
        await self.store.raw(new)
        job = await self.job(kind="catalog")
        await self.store.checkpoint(job, {"cursor": "keep-progress"})
        m = market("polymarket", {"id": "m1", "conditionId": "c1"}, old["received_at"])
        await self.store.commit_page(job, old, {"cursor": "keep-progress"}, markets=[m])
        # A later case refers to the oldest receipt, so capacity eviction must
        # remove both versions and the case despite its newer creation time.
        await self.store.save_case({"id": "pinned", "venue": "polymarket", "market_id": "c1",
                                    "rules_raw_id": old["id"]})
        before = (await self.store.fetch("SELECT pg_total_relation_size('surveillance_markets') AS n"))[0]["n"]
        async with await psycopg.AsyncConnection.connect(self.dsn, autocommit=True,
                                                         row_factory=psycopg.rows.dict_row) as c:
            self.assertEqual(await evict_batch(c, 1), 1)
            self.assertEqual(await sweep_orphans(c, self.folder.name), 0)
            for table in TABLES:
                await c.execute(sql.SQL("VACUUM (FULL, ANALYZE) {}").format(sql.Identifier(table)))
        self.assertTrue(Path(new["path"]).exists())
        self.assertEqual(RawArchive.read(new), b"shared")
        self.assertFalse(await self.store.fetch("SELECT * FROM surveillance_cases"))
        self.assertFalse(await self.store.fetch("SELECT * FROM surveillance_case_versions"))
        self.assertFalse(await self.store.fetch("SELECT * FROM surveillance_markets"))
        self.assertFalse(await self.store.fetch("SELECT * FROM surveillance_rules"))
        self.assertEqual((await self.store.fetch("SELECT checkpoint FROM surveillance_jobs"))[0]["checkpoint"]["cursor"],
                         "keep-progress")
        after = (await self.store.fetch("SELECT pg_total_relation_size('surveillance_markets') AS n"))[0]["n"]
        self.assertLess(after, before)

    async def test_capacity_trigger_blocks_api_then_evicts_oldest_and_recovers(self):
        from dataclasses import replace
        from surveillance.capacity import enforce, raw_bytes
        old = self.archive.write("polymarket", "old", {}, 200, os.urandom(65536), "2020-01-01T00:00:00+00:00")
        new = self.archive.write("polymarket", "new", {}, 200, os.urandom(65536))
        await self.store.raw(old)
        await self.store.raw(new)
        settings = replace(self.settings, raw_max_bytes=raw_bytes(self.folder.name), api_token="capacity-test")
        app = create_app(settings)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                     headers={"Authorization": "Bearer capacity-test"}) as client:
            response = await client.post("/replay", json={"venue": "polymarket", "market_id": "c1", "as_of": now()})
            self.assertEqual(response.status_code, 503)
            result = await enforce(self.store, settings, batch_limit=1, max_batches=1)
            self.assertEqual(result["evicted_receipts"], 1)
            self.assertFalse(result["blocked"])
            self.assertFalse(Path(old["path"]).exists())
            self.assertTrue(Path(new["path"]).exists())
            self.assertEqual((await client.get("/capacity")).status_code, 200)
            response = await client.post("/replay", json={"venue": "polymarket", "market_id": "c1", "as_of": now()})
            self.assertEqual(response.status_code, 200)

    async def test_capacity_exclusive_lock_serializes_other_transactions(self):
        from surveillance.capacity import LOCK
        async with await psycopg.AsyncConnection.connect(self.dsn, autocommit=True) as c:
            await c.execute("SELECT pg_advisory_lock(%s)", (LOCK,))
            task = asyncio.create_task(self.store.fetch("SELECT 1 AS n"))
            await asyncio.sleep(.05)
            self.assertFalse(task.done())
            await c.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
            self.assertEqual((await asyncio.wait_for(task, 2))[0]["n"], 1)

    async def test_light_catalog_details_and_restart_scope(self):
        requests = []
        def handler(request):
            requests.append((request.url.path, dict(request.url.params)))
            if request.url.path.endswith("/markets/p1"):
                return httpx.Response(200, json={"id": "p1", "conditionId": "c1", "description": "rule prose",
                    "question": "Policy announcement", "closed": False})
            return httpx.Response(200, json={"markets": [{"id": "p1", "conditionId": "c1", "description": "rule prose",
                "question": "Policy announcement", "closed": False}], "next_cursor": None})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        worker = Worker(self.settings, Collector(self.store, self.archive, 0, client))
        job = await self.job("catalog-test", "catalog")
        job["payload"] = {"closed": False, "scope": "active-v2"}
        await worker.ingest(job)
        self.assertFalse(await self.store.fetch("SELECT * FROM surveillance_rules"))
        doc = (await self.store.fetch("SELECT document FROM surveillance_markets"))[0]["document"]
        self.assertNotIn("rules", doc)
        self.assertNotIn("tokens", doc)
        await self.store.release(job, 3600)
        await worker.schedule("polymarket")
        detail = await self.store.claim()
        self.assertEqual(detail["kind"], "details")
        await worker.ingest(detail)
        rules = await self.store.fetch("SELECT document FROM surveillance_rules")
        self.assertEqual(rules[0]["document"]["rules"]["description"], "rule prose")
        self.assertEqual(requests[-1][0], "/markets/p1")
        await self.store.enqueue("catalog:legacy", "catalog", "kalshi", {})
        await worker.seed()
        self.assertFalse((await self.store.fetch("SELECT enabled FROM surveillance_jobs WHERE id='catalog:legacy'"))[0]["enabled"])
        active = await self.store.fetch("SELECT * FROM surveillance_jobs WHERE kind='catalog' AND enabled")
        self.assertEqual({r["payload"]["scope"] for r in active}, {"active-v2"})
        await worker.collector.close()

    async def test_kalshi_discovery_excludes_combos_and_closed_but_details_allow_history(self):
        def handler(request):
            if request.url.path.endswith("/OLD"):
                return httpx.Response(200, json={"market": {"ticker": "OLD", "event_ticker": "E", "status": "finalized", "result": "yes"}})
            self.assertEqual(request.url.params["status"], "open")
            self.assertEqual(request.url.params["mve_filter"], "exclude")
            return httpx.Response(200, json={"markets": [], "cursor": ""})
        worker = Worker(self.settings, Collector(self.store, self.archive,0,httpx.AsyncClient(transport=httpx.MockTransport(handler))))
        job = await self.job("k", "catalog", "kalshi")
        job["payload"] = {"scope": "active-v2"}
        await worker.ingest(job)
        raw, rows, _ = await worker.collector.page({"venue":"kalshi","kind":"details","checkpoint":{},"payload":{"market_id":"OLD"}})
        self.assertEqual(rows[0]["status"], "finalized")
        await worker.collector.close()

    async def test_reset_only_owned_dataset_and_raw_dir(self):
        from surveillance.maintenance import reset_test_dataset
        async with self.store.connection() as c:
            await c.execute("CREATE TABLE unrelated(note text)")
            await c.execute("INSERT INTO unrelated VALUES('keep')")
        raw = self.archive.write("kalshi", "test", {},200,b'{}')
        await self.store.raw(raw)
        await self.job()
        await reset_test_dataset(self.store,self.folder.name)
        self.assertFalse(await self.store.fetch("SELECT * FROM surveillance_raw"))
        self.assertFalse(await self.store.fetch("SELECT * FROM surveillance_jobs"))
        self.assertEqual((await self.store.fetch("SELECT note FROM unrelated"))[0]["note"],"keep")
        self.assertFalse(Path(raw["path"]).exists())

    async def test_manual_backfill_resolves_condition_and_stays_out_of_scheduler(self):
        from argparse import Namespace
        from unittest.mock import patch
        from surveillance.cli import execute
        def handler(request):
            if request.url.path.endswith("/markets/past"):
                return httpx.Response(200,json={"id":"past","conditionId":"old-condition","closed":True,
                    "description":"historical rules","umaResolutionStatus":"resolved"})
            self.assertEqual(request.url.params["condition"],"old-condition")
            return httpx.Response(200,json={"data":[],"pagination":{"has_more":False,"next_cursor":None}})
        with patch("surveillance.cli.Settings.env",return_value=self.settings):
            await execute(Namespace(command="backfill",venue="polymarket",market="past",since="2025-01-01T00:00:00+00:00"))
        worker=Worker(self.settings,Collector(self.store,self.archive,0,httpx.AsyncClient(transport=httpx.MockTransport(handler))))
        self.assertTrue(await worker.run_once())
        self.assertTrue(await worker.run_once())
        jobs=await self.store.fetch("SELECT * FROM surveillance_jobs ORDER BY kind")
        self.assertTrue(all(not j["enabled"] for j in jobs))
        self.assertTrue(all(j["checkpoint"].get("completed_at") for j in jobs))
        self.assertEqual(len(await self.store.fetch("SELECT * FROM surveillance_rules")),1)
        await worker.schedule("polymarket")
        self.assertFalse(any(j["enabled"] for j in await self.store.fetch("SELECT * FROM surveillance_jobs WHERE payload->>'manual'='true'")))
        await worker.collector.close()

    async def test_automatic_worker_suppresses_real_tiny_cash_anomaly(self):
        cutoff=datetime.now(timezone.utc).replace(second=0,microsecond=0)
        observed=(cutoff-timedelta(seconds=1)).isoformat()
        job=await self.job()
        raw=self.archive.write("polymarket","test",{},200,b'{}',observed)
        rows=[]
        for i in range(12):
            r=dict(poly(),size=10,price=.001,timestamp=int((cutoff-timedelta(seconds=90+i*60)).timestamp()))
            rows.append(dict(trade("polymarket",r,observed),id=f"base{i}"))
        for i in range(10):
            r=dict(poly(),size=1000,price=.001,timestamp=int((cutoff-timedelta(seconds=30-i)).timestamp()))
            rows.append(dict(trade("polymarket",r,observed),id=f"spike{i}"))
        await self.store.commit_page(job,raw,{},trades=rows)
        await self.store.release(job,3600)
        await self.store.enqueue("detect-test","detect","polymarket",{"market_id":"c1"})
        worker=Worker(self.settings)
        await worker.run_once()
        checkpoint=(await self.store.fetch("SELECT checkpoint FROM surveillance_jobs WHERE id='detect-test'"))[0]["checkpoint"]
        self.assertGreater(checkpoint["detected"],0)
        self.assertGreater(checkpoint["suppressed_by_cost_floor"],0)
        self.assertEqual(checkpoint["new_cases"],0)
        self.assertFalse(await self.store.fetch("SELECT * FROM surveillance_cases"))
        await worker.collector.close()

    async def test_completed_active_walk_expires_unseen_index_but_keeps_manual_and_case(self):
        old=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        j=await self.job('seed','catalog')
        raw=self.archive.write('polymarket','test',{},200,b'{}',old)
        markets=[market('polymarket',{'id':k,'conditionId':k},old) for k in ('gone','manual','case')]
        await self.store.commit_page(j,raw,{},markets=markets,detailed=False)
        await self.store.enqueue('manual-ref','details','polymarket',{'manual':True,'catalog_id':'manual'})
        await self.store.save_case({'id':'pinned','venue':'polymarket','market_id':'case'})
        new=self.archive.write('polymarket','test',{},200,b'{"new":1}')
        checkpoint={}
        await self.store.commit_page(j,new,checkpoint,markets=[],detailed=False,catalog_expire_before=new['received_at'])
        self.assertEqual({r['id'] for r in await self.store.fetch('SELECT id FROM surveillance_markets')},{'manual','case'})
        self.assertEqual(checkpoint['expired_unseen_index_rows'],1)
