import asyncio
from collections import Counter
from datetime import datetime, timezone, timedelta
import logging

from .collectors import Collector, ContractError
from .discovery import Selector
from .investigations import replay, ReplayCapacityError
from .maintenance import prune
from .capacity import CapacityGuard
from .normalization import market, trade, digest
from .storage import Store, RawArchive

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, settings, collector=None):
        self.settings = settings
        self.store = Store(settings.database_url)
        self.capacity = CapacityGuard(self.store, settings)
        self.collector = collector or Collector(self.store, RawArchive(settings.raw_dir), settings.request_interval)

    async def seed(self):
        await self.store.enqueue("maintenance", "maintenance", "system", {})
        for closed in (False, True):
            await self.store.enqueue(f"catalog:polymarket:{closed}", "catalog", "polymarket", {"closed": closed})
        await self.store.enqueue("catalog:kalshi", "catalog", "kalshi", {})
        for venue in ("polymarket", "kalshi"):
            await self.store.enqueue(f"schedule:{venue}", "schedule", venue, {})

    async def schedule(self, venue):
        selector = Selector(self.settings.contracts_per_venue, self.settings.exploration_fraction)
        async with self.store.connection() as c:
            async with c.cursor(name="selection") as cursor:
                cursor.itersize = 256
                await cursor.execute("""SELECT document FROM surveillance_markets WHERE venue=%s
                    AND document->>'closed'='false'""", (venue,))
                async for row in cursor:
                    selector.add(row["document"])
        chosen = selector.result()
        count = (await self.store.fetch("SELECT count(*) AS n FROM surveillance_markets WHERE venue=%s", (venue,)))[0]["n"]
        keys = []
        for m in chosen:
            key = m["condition_id"] or m["id"]
            for kind in ("trades", "detect"):
                job_id = f"{kind}:{venue}:{key}"
                keys.append(job_id)
                await self.store.enqueue(job_id, kind, venue, {"market_id": key})
        async with self.store.connection() as c:
            # Disabled jobs keep checkpoints and may resume on a later rotation.
            await c.execute("""UPDATE surveillance_jobs SET enabled=(id=ANY(%s)),
                due_at=CASE WHEN NOT enabled AND id=ANY(%s) THEN now() ELSE due_at END
                WHERE venue=%s AND kind IN ('trades','detect')""", (keys, keys, venue))
        await self.store.coverage(venue, "budget", {"catalog_rows": count, "selected_contracts": len(chosen),
            "budget": self.settings.contracts_per_venue, "exploration_fraction": self.settings.exploration_fraction,
            "limitations": ["Heuristic category ranking; no verified event mapping yet",
                             "REST only; order books and broadcast feeds not collected",
                             "Kalshi historical archive catalog not yet integrated"]})

    async def ingest(self, job):
        cp = dict(job["checkpoint"])
        if job["kind"] == "trades" and not cp.get("since"):
            cp["since"] = int((datetime.now(timezone.utc) - timedelta(hours=13)).timestamp())
            await self.store.checkpoint(job, cp)
            await self.store.coverage(job["venue"], "bootstrap_horizon", {"market_id": job["payload"]["market_id"],
                "since": cp["since"], "older_history": "not_collected"}, job["id"])
        for _ in range(self.settings.pages_per_job):
            if not await self.capacity.check():
                return 60
            job["checkpoint"] = cp
            raw, rows, cursor = await self.collector.page(job)
            cursor_hash = digest(cursor) if cursor else None
            seen = cp.get("seen_cursors", [])
            if cursor_hash and cursor_hash in seen:
                raise ContractError("Pagination cursor cycle; checkpoint preserved")
            cp["seen_cursors"] = (seen + [cursor_hash])[-1000:] if cursor_hash else []
            if job["kind"] == "catalog":
                markets = [market(job["venue"], r, raw["received_at"]) for r in rows]
                cp = dict(cp, cursor=cursor, pages=cp.get("pages", 0) + 1)
                if not cursor:
                    cp = {"completed_at": raw["received_at"], "pages": 0}
                await self.store.commit_page(job, raw, cp, markets=markets)
            else:
                normalized = [trade(job["venue"], r, raw["received_at"]) for r in rows]
                previous = cp.get("last_time")
                counts = Counter(cp.get("counts", {}))
                accepted = []
                exhausted = False
                high_watermark = cp.get("high_watermark", cp["since"])
                for t in normalized:
                    ts = int(datetime.fromisoformat(t["event_time"]).timestamp())
                    if previous is not None and ts > previous:
                        raise ContractError("Trade feed not ordered newest-first; cannot safely checkpoint")
                    if ts < cp["since"]:
                        exhausted = True
                        break
                    if ts != previous:
                        counts.clear()
                    previous = ts
                    counts[t["identity"]] += 1
                    t["id"] = t["identity"] + (f":{counts[t['identity']]}" if job["venue"] == "polymarket" else "")
                    t["raw_id"] = raw["id"]
                    accepted.append(t)
                    high_watermark = max(high_watermark, ts)
                cp.update(cursor=cursor, high_watermark=high_watermark, last_time=previous, counts=dict(counts))
                if exhausted or not cursor:
                    cp = {"since": max(cp["since"], high_watermark - 300), "completed_at": raw["received_at"]}
                    cursor = None
                await self.store.commit_page(job, raw, cp, trades=accepted)
            if not cursor:
                await self.store.coverage(job["venue"], "walk_completed", {"kind": job["kind"],
                    "market_id": job["payload"].get("market_id"), "checkpoint": cp,
                    "meaning": "Completed requested walk only; not proof of upstream completeness"}, job["id"])
                if job["kind"] == "trades":
                    return self.settings.poll_seconds
                return self.settings.closed_catalog_seconds if job["payload"].get("closed") else self.settings.catalog_seconds
        await self.store.coverage(job["venue"], "walk_pending", {"kind": job["kind"],
            "reason": "page budget reached", "cursor_saved": True}, job["id"])
        return 1

    async def run_once(self):
        if not await self.capacity.check():
            return False
        job = await self.store.claim()
        if not job:
            return False
        try:
            if job["kind"] == "maintenance":
                result = await prune(self.store, self.settings.retention_days)
                await self.store.checkpoint(job, result)
                delay = 3600
            elif job["kind"] == "schedule":
                await self.schedule(job["venue"])
                delay = 300
            elif job["kind"] == "detect":
                # Fixed UTC minute makes duplicate executions idempotent.
                as_of = datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
                cases = await replay(self.store, job["venue"], job["payload"]["market_id"], as_of, persist=False, max_trades=self.settings.replay_max_trades)
                new_cases = 0
                for case in cases:
                    new_cases += int(await self.store.save_candidate(case, self.settings.case_cooldown_seconds))
                await self.store.checkpoint(job, {"as_of": as_of, "detected": len(cases),
                    "new_cases": new_cases, "coalesced": len(cases) - new_cases})
                if cases:
                    # Escalation stays within the selected per-platform contract budget.
                    async with self.store.connection() as c:
                        await c.execute("""UPDATE surveillance_jobs SET due_at=LEAST(due_at,now()) WHERE id=%s""",
                            (f"trades:{job['venue']}:{job['payload']['market_id']}",))
                delay = 60
            else:
                delay = await self.ingest(job)
            await self.store.release(job, delay)
        except asyncio.CancelledError:
            await self.store.release(job, 0, "worker interrupted; resume checkpoint")
            raise
        except Exception as exc:
            # Do not emit credentials, response bodies or query strings into logs.
            detail = str(exc) if isinstance(exc, (ContractError, ReplayCapacityError)) else "collection/job failed; inspect raw evidence"
            reason = f"{type(exc).__name__}: {detail}"
            logger.warning("Job %s failed (%s)", job["id"], type(exc).__name__)
            await self.store.coverage(job["venue"], "error", {"error": reason, "checkpoint_preserved": True}, job["id"])
            backoff = min(3600, 60 * 2 ** min(job["failures"], 5))
            await self.store.release(job, max(backoff, getattr(exc, "retry_after", 0)), reason)
        return True

    async def run(self, once=False):
        await self.seed()
        try:
            if once:
                return await self.run_once()
            while True:
                if not await self.run_once():
                    await asyncio.sleep(1)
        finally:
            await self.collector.close()
